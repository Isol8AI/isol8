//! Local loopback WebSocket proxy for API Gateway auth injection.
//!
//! runNodeHost() / our node client connects to ws://127.0.0.1:{port}.
//! This proxy opens wss://{target}?token={jwt} to API Gateway.
//! All messages are relayed bidirectionally.

use futures_util::{SinkExt, StreamExt};
use std::sync::Arc;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::Mutex;
use tokio_tungstenite::{connect_async, accept_async};

/// Start the local loopback proxy. Returns a handle to stop it.
pub async fn start_proxy(
    port: u16,
    target_ws_url: &str,
    clerk_jwt: &str,
) -> Result<ProxyHandle, Box<dyn std::error::Error + Send + Sync>> {
    let addr = format!("127.0.0.1:{}", port);
    let listener = TcpListener::bind(&addr).await?;
    let upstream_url = format!("{}?token={}", target_ws_url, clerk_jwt);
    let upstream_url = Arc::new(upstream_url);

    let stop = Arc::new(Mutex::new(false));
    let stop_clone = stop.clone();

    let handle = tokio::spawn(async move {
        loop {
            let should_stop = *stop_clone.lock().await;
            if should_stop {
                break;
            }

            let accept = tokio::select! {
                result = listener.accept() => result,
                _ = tokio::time::sleep(tokio::time::Duration::from_millis(100)) => continue,
            };

            match accept {
                Ok((stream, _)) => {
                    let url = upstream_url.clone();
                    tokio::spawn(async move {
                        if let Err(e) = handle_connection(stream, &url).await {
                            eprintln!("[node-proxy] Connection error: {}", e);
                        }
                    });
                }
                Err(e) => {
                    eprintln!("[node-proxy] Accept error: {}", e);
                }
            }
        }
    });

    Ok(ProxyHandle {
        stop,
        _task: handle,
    })
}

async fn handle_connection(
    stream: TcpStream,
    upstream_url: &str,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let client_ws = accept_async(stream).await?;
    let (upstream_ws, _) = connect_async(upstream_url).await?;

    let (mut client_write, mut client_read) = client_ws.split();
    let (mut upstream_write, mut upstream_read) = upstream_ws.split();

    // Relay: client → upstream
    let client_to_upstream = tokio::spawn(async move {
        while let Some(Ok(msg)) = client_read.next().await {
            if msg.is_close() {
                break;
            }
            if upstream_write.send(msg).await.is_err() {
                break;
            }
        }
    });

    // Relay: upstream → client
    let upstream_to_client = tokio::spawn(async move {
        while let Some(Ok(msg)) = upstream_read.next().await {
            if msg.is_close() {
                break;
            }
            if client_write.send(msg).await.is_err() {
                break;
            }
        }
    });

    // Wait for either direction to close
    tokio::select! {
        _ = client_to_upstream => {},
        _ = upstream_to_client => {},
    }

    Ok(())
}

pub struct ProxyHandle {
    stop: Arc<Mutex<bool>>,
    _task: tokio::task::JoinHandle<()>,
}

impl ProxyHandle {
    pub async fn stop(&self) {
        *self.stop.lock().await = true;
    }
}
