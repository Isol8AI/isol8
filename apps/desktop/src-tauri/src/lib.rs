mod exec_approvals;
mod node_client;
mod node_invoke;
mod node_proxy;
mod tray;

use std::sync::Mutex;
use tauri::{Emitter, Manager, State, Url};
use tauri_plugin_deep_link::DeepLinkExt;

/// Shared auth token state
pub struct AuthState {
    pub token: Mutex<Option<String>>,
}

/// Node connection status + handles for cleanup
pub struct NodeState {
    pub status: Mutex<String>,
    pub proxy_handle: Mutex<Option<node_proxy::ProxyHandle>>,
}

const PROXY_PORT: u16 = 18790;

/// Called by the web app to send the Clerk JWT to the Rust backend.
/// Starts the node-host connection via the local loopback proxy.
#[tauri::command]
fn send_auth_token(
    token: String,
    state: State<'_, AuthState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let mut t = state.token.lock().map_err(|e| e.to_string())?;
    let is_first = t.is_none();
    *t = Some(token.clone());
    println!("[auth] Received Clerk JWT ({} chars)", token.len());

    // Only start node-host on the first token. Subsequent tokens are from
    // WebSocket reconnects — the proxy is already running.
    if !is_first {
        println!("[auth] Token updated (proxy already running)");
        return Ok(());
    }

    // Use the same WebSocket URL as the frontend.
    // Dev builds point at ws-dev, prod at ws. Controlled by env var at build time.
    let ws_url = option_env!("ISOL8_WS_URL").unwrap_or("wss://ws-dev.isol8.co");

    let app_handle = app.clone();
    let ws_url = ws_url.to_string();
    tauri::async_runtime::spawn(async move {
        if let Err(e) = start_node_host(&app_handle, &ws_url, &token).await {
            eprintln!("[node] Failed to start: {}", e);
            update_node_status(&app_handle, "error");
        }
    });

    Ok(())
}

async fn start_node_host(
    app: &tauri::AppHandle,
    ws_url: &str,
    clerk_jwt: &str,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    update_node_status(app, "connecting");

    // Step 1: Start loopback proxy (injects JWT into API Gateway URL)
    let proxy_handle = node_proxy::start_proxy(PROXY_PORT, ws_url, clerk_jwt).await?;
    println!("[node] Proxy started on 127.0.0.1:{}", PROXY_PORT);

    // Step 2: Start node client pointing at local proxy
    let proxy_url = format!("ws://127.0.0.1:{}", PROXY_PORT);
    let mut client = node_client::NodeClient::new(&proxy_url, "Isol8 Desktop");
    let mut invoke_rx = client.start().await?;

    update_node_status(app, "connected");
    println!("[node] Node client started, listening for invoke requests");

    // Store proxy handle for cleanup
    if let Some(state) = app.try_state::<NodeState>() {
        *state.proxy_handle.lock().unwrap() = Some(proxy_handle);
    }

    // Step 3: Handle invoke requests in background
    tokio::spawn(async move {
        while let Some(request) = invoke_rx.recv().await {
            println!("[node] Invoke: {} ({})", request.command, request.id);
            node_invoke::handle_invoke(&client, request).await;
        }
        println!("[node] Invoke receiver closed");
    });

    Ok(())
}

fn update_node_status(app: &tauri::AppHandle, status: &str) {
    let label = match status {
        "connecting" => "Node: Connecting...",
        "connected" => "Node: Connected",
        "error" => "Node: Error",
        _ => "Ready",
    };
    tray::update_tray_status(app, label);
    let _ = app.emit("node:status", status);

    if let Some(state) = app.try_state::<NodeState>() {
        *state.status.lock().unwrap() = status.into();
    }
}

/// Returns true — lets the web app detect it's running in the desktop app.
#[tauri::command]
fn is_desktop() -> bool {
    true
}

/// Returns the current node connection status.
#[tauri::command]
fn get_node_status(state: State<'_, NodeState>) -> String {
    state.status.lock().unwrap().clone()
}

/// OAuth domains that must open in the system browser.
const OAUTH_DOMAINS: &[&str] = &["accounts.google.com", "appleid.apple.com"];

/// Desktop callback URL — the page creates a sign-in token and deep links back.
/// Not middleware-protected, so it works whether or not the user is signed in yet.
const DESKTOP_CALLBACK_URL: &str = "https://dev.isol8.co/auth/desktop-callback?x-vercel-protection-bypass=BWitr6v05GtUmGWJsjlfkqrOGyb68tR8&x-vercel-set-bypass-cookie=samesitenone";

fn is_oauth_url(url: &Url) -> bool {
    let host = url.host_str().unwrap_or("");
    OAUTH_DOMAINS
        .iter()
        .any(|d| host == *d || host.ends_with(&format!(".{}", d)))
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(
            tauri::plugin::Builder::<tauri::Wry>::new("oauth-intercept")
                .on_navigation(|_window, url| {
                    if is_oauth_url(url) {
                        let _ = open::that(DESKTOP_CALLBACK_URL);
                        return false;
                    }
                    true
                })
                .build(),
        )
        .manage(AuthState {
            token: Mutex::new(None),
        })
        .manage(NodeState {
            status: Mutex::new("disconnected".into()),
            proxy_handle: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            send_auth_token,
            is_desktop,
            get_node_status,
        ])
        .setup(|app| {
            tray::create_tray(app.handle())?;

            // Debug: check if __TAURI__ is available on the page
            if let Some(window) = app.get_webview_window("main") {
                let w = window.clone();
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_secs(5));
                    let _ = w.eval("console.log('[isol8-debug] __TAURI__ exists:', typeof window.__TAURI__); if(window.__TAURI__) { window.__TAURI__.core.invoke('send_auth_token', {token: 'debug-test'}); }");
                });
            }

            // Override window.open in the WebView so OAuth popups open
            // in the system browser. WKWebView silently blocks popups,
            // so Clerk's Google OAuth popup never opens without this.
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.eval(&format!(
                    r#"
                    (function() {{
                        const originalOpen = window.open;
                        window.open = function(url, target, features) {{
                            if (url && (url.includes('accounts.google.com') || url.includes('clerk'))) {{
                                // Redirect to desktop sign-in flow instead
                                window.location.href = '{}';
                                return null;
                            }}
                            return originalOpen.call(window, url, target, features);
                        }};
                    }})();
                    "#,
                    DESKTOP_CALLBACK_URL
                ));
            }

            // Handle deep links (isol8:// protocol)
            let app_handle = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                let urls = event.urls();
                for url_obj in urls {
                    let url_str = url_obj.to_string();
                    if url_str.starts_with("isol8://auth") {
                        if let Ok(parsed) = url::Url::parse(&url_str) {
                            if let Some(ticket) = parsed
                                .query_pairs()
                                .find(|(k, _)| k == "ticket")
                                .map(|(_, v)| v.to_string())
                            {
                                if let Some(window) = app_handle.get_webview_window("main") {
                                    let _ = window.emit("auth:sign-in-ticket", &ticket);
                                }
                            }
                        }
                    }

                    if let Some(window) = app_handle.get_webview_window("main") {
                        let _ = window.unminimize();
                        let _ = window.set_focus();
                    }
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
