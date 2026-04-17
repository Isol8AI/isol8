//! Lightweight OpenClaw node client.
//!
//! Ported from OpenClaw's GatewayClient (src/gateway/client.ts) and
//! macOS companion app (GatewayNodeSession.swift). Implements the
//! OpenClaw WebSocket protocol for role:"node" connections.
//!
//! Handles: connect handshake, node.invoke.request dispatch, reconnection.

use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use tokio::sync::{mpsc, Mutex, oneshot};
use tokio_tungstenite::{connect_async, tungstenite::Message};
use uuid::Uuid;

// --- Types (from OpenClaw protocol schema) ---

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NodeInvokeRequest {
    pub id: String,
    #[serde(rename = "nodeId")]
    pub node_id: String,
    pub command: String,
    #[serde(rename = "paramsJSON")]
    pub params_json: Option<String>,
    #[serde(rename = "timeoutMs")]
    pub timeout_ms: Option<u64>,
}

#[derive(Debug, Serialize)]
pub struct NodeInvokeResult {
    pub id: String,
    #[serde(rename = "nodeId")]
    pub node_id: String,
    pub ok: bool,
    #[serde(rename = "payloadJSON", skip_serializing_if = "Option::is_none")]
    pub payload_json: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<InvokeError>,
}

#[derive(Debug, Serialize)]
pub struct InvokeError {
    pub code: String,
    pub message: String,
}

// --- Node Client ---

type PendingMap = Arc<Mutex<HashMap<String, oneshot::Sender<Value>>>>;
type InvokeSender = mpsc::UnboundedSender<NodeInvokeRequest>;

pub struct NodeClient {
    /// Shared so callers can update the URL (e.g. with a refreshed JWT) and
    /// the next reconnect picks it up. Guard is never held across await.
    url: Arc<RwLock<String>>,
    display_name: String,
    write_tx: Option<mpsc::UnboundedSender<Message>>,
    pending: PendingMap,
    stop_tx: Option<oneshot::Sender<()>>,
}

impl NodeClient {
    pub fn new(url: &str, display_name: &str) -> Self {
        Self::with_shared_url(
            Arc::new(RwLock::new(url.to_string())),
            display_name,
        )
    }

    /// Construct a client backed by a shared URL handle. Callers that need to
    /// rotate the token can keep a clone of the Arc and write to it; the
    /// connection loop re-reads before each reconnect.
    pub fn with_shared_url(url: Arc<RwLock<String>>, display_name: &str) -> Self {
        Self {
            url,
            display_name: display_name.to_string(),
            write_tx: None,
            pending: Arc::new(Mutex::new(HashMap::new())),
            stop_tx: None,
        }
    }

    /// Start the client. Returns a receiver for invoke requests.
    pub async fn start(&mut self) -> Result<mpsc::UnboundedReceiver<NodeInvokeRequest>, Box<dyn std::error::Error + Send + Sync>> {
        let (invoke_tx, invoke_rx) = mpsc::unbounded_channel::<NodeInvokeRequest>();
        let (stop_tx, stop_rx) = oneshot::channel::<()>();
        let (write_tx, write_rx) = mpsc::unbounded_channel::<Message>();

        self.write_tx = Some(write_tx.clone());
        self.stop_tx = Some(stop_tx);

        let url = self.url.clone();
        let display_name = self.display_name.clone();
        let pending = self.pending.clone();

        tokio::spawn(async move {
            connection_loop(url, display_name, write_tx, write_rx, invoke_tx, pending, stop_rx).await;
        });

        Ok(invoke_rx)
    }

    /// Send a node.invoke.result back to the gateway.
    pub async fn send_invoke_result(&self, result: NodeInvokeResult) -> Result<(), String> {
        let id = Uuid::new_v4().to_string();
        let frame = json!({
            "type": "req",
            "id": id,
            "method": "node.invoke.result",
            "params": result,
        });
        self.send_frame(frame).await
    }

    /// Send a JSON frame to the gateway.
    async fn send_frame(&self, frame: Value) -> Result<(), String> {
        if let Some(tx) = &self.write_tx {
            tx.send(Message::Text(frame.to_string().into()))
                .map_err(|e| format!("Send failed: {}", e))
        } else {
            Err("Not connected".into())
        }
    }

    pub async fn stop(&mut self) {
        if let Some(tx) = self.stop_tx.take() {
            let _ = tx.send(());
        }
        self.write_tx = None;
    }
}

// --- Connection loop with reconnection ---

async fn connection_loop(
    url: Arc<RwLock<String>>,
    display_name: String,
    write_tx: mpsc::UnboundedSender<Message>,
    mut write_rx: mpsc::UnboundedReceiver<Message>,
    invoke_tx: InvokeSender,
    pending: PendingMap,
    mut stop_rx: oneshot::Receiver<()>,
) {
    let mut reconnect_delay = std::time::Duration::from_secs(1);
    let max_delay = std::time::Duration::from_secs(30);

    // write_rx lives for the entire loop so that it stays paired with the
    // write_tx held by NodeClient. Prior design moved it into a per-connection
    // spawn and replaced it with a brand-new unpaired channel on reconnect —
    // after the first drop, every send_frame silently went nowhere. Keeping
    // ownership here and multiplexing via tokio::select! avoids that entirely.
    loop {
        // Snapshot the current URL so a mid-connect token update is picked up
        // on the very next reconnect attempt.
        let current_url = url.read().unwrap().clone();
        println!("[node-client] Connecting...");

        let ws = tokio::select! {
            _ = &mut stop_rx => {
                println!("[node-client] Stop signal received during connect");
                return;
            }
            res = connect_async(&current_url) => match res {
                Ok((ws, _)) => ws,
                Err(e) => {
                    eprintln!("[node-client] Connection failed: {}", e);
                    // Backoff, respecting stop.
                    tokio::select! {
                        _ = &mut stop_rx => return,
                        _ = tokio::time::sleep(reconnect_delay) => {}
                    }
                    reconnect_delay = std::cmp::min(reconnect_delay * 2, max_delay);
                    continue;
                }
            }
        };

        println!("[node-client] WebSocket connected");
        reconnect_delay = std::time::Duration::from_secs(1);

        let (mut ws_write, mut ws_read) = ws.split();

        // Process messages until either the socket dies or we get a stop.
        // write_rx stays borrowed from the outer scope — no ownership move, no
        // pairing loss on reconnect.
        let drop_reason = loop {
            tokio::select! {
                // Clean shutdown.
                _ = &mut stop_rx => {
                    let _ = ws_write.close().await;
                    return;
                }

                // Outbound frame from NodeClient → push to the socket.
                Some(msg) = write_rx.recv() => {
                    if let Err(e) = ws_write.send(msg).await {
                        break format!("ws_write failed: {}", e);
                    }
                }

                // Inbound frame from the gateway → dispatch.
                next = ws_read.next() => {
                    match next {
                        Some(Ok(Message::Text(text))) => {
                            handle_message(
                                &text,
                                &display_name,
                                &invoke_tx,
                                &pending,
                                &write_tx,
                            ).await;
                        }
                        Some(Ok(_)) => {
                            // Ignore non-text frames (ping/pong handled by the lib).
                        }
                        Some(Err(e)) => break format!("ws_read error: {}", e),
                        None => break "ws_read closed".to_string(),
                    }
                }
            }
        };

        eprintln!("[node-client] Disconnected ({}); reconnecting", drop_reason);

        // Backoff before the next reconnect, respecting stop.
        tokio::select! {
            _ = &mut stop_rx => return,
            _ = tokio::time::sleep(reconnect_delay) => {}
        }
        reconnect_delay = std::cmp::min(reconnect_delay * 2, max_delay);
    }
}

async fn handle_message(
    text: &str,
    display_name: &str,
    invoke_tx: &InvokeSender,
    pending: &PendingMap,
    write_tx: &mpsc::UnboundedSender<Message>,
) {
    let Ok(frame) = serde_json::from_str::<Value>(text) else {
        return;
    };

    let msg_type = frame.get("type").and_then(|v| v.as_str()).unwrap_or("");

    match msg_type {
        "event" => {
            let event = frame.get("event").and_then(|v| v.as_str()).unwrap_or("");

            if event == "connect.challenge" {
                // Send connect request with role:"node"
                let id = Uuid::new_v4().to_string();
                let connect_msg = json!({
                    "type": "req",
                    "id": id,
                    "method": "connect",
                    "params": {
                        "minProtocol": 3,
                        "maxProtocol": 3,
                        "client": {
                            "id": "node-host",
                            "displayName": display_name,
                            "version": "1.0.0",
                            "platform": std::env::consts::OS,
                            "mode": "node",
                            "instanceId": Uuid::new_v4().to_string(),
                        },
                        "role": "node",
                        "scopes": [],
                        "caps": ["system"],
                        "commands": [
                            "system.run.prepare",
                            "system.run",
                            "system.which",
                            "system.execApprovals.get",
                            "system.execApprovals.set",
                        ],
                        "pathEnv": std::env::var("PATH").unwrap_or_default(),
                        "auth": {},
                    },
                });
                let _ = write_tx.send(Message::Text(connect_msg.to_string().into()));
            } else if event == "node.invoke.request" {
                if let Some(payload) = frame.get("payload") {
                    if let Ok(req) = serde_json::from_value::<NodeInvokeRequest>(payload.clone()) {
                        let _ = invoke_tx.send(req);
                    }
                }
            }
            // tick events — ignore (keepalive)
        }
        "res" => {
            let id = frame.get("id").and_then(|v| v.as_str()).unwrap_or("");
            let ok = frame.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);

            if ok {
                // Check if it's a hello-ok (connect response)
                if let Some(payload) = frame.get("payload") {
                    if payload.get("protocol").is_some() {
                        println!("[node-client] Connected to gateway (hello-ok)");
                    }
                }
            }

            // Resolve pending request
            let mut pending = pending.lock().await;
            if let Some(sender) = pending.remove(id) {
                let _ = sender.send(frame);
            }
        }
        _ => {}
    }
}
