mod exec_approvals;
mod node_client;
mod node_invoke;
mod tray;

use std::sync::{Arc, Mutex, RwLock};
use tauri::{Emitter, Manager, State, Url};
use tauri_plugin_deep_link::DeepLinkExt;

/// Shared auth token state
pub struct AuthState {
    pub token: Mutex<Option<String>>,
    /// Shared handle to the running node client's gateway URL. Updated whenever
    /// a fresh JWT arrives so the next reconnect uses current auth.
    pub gateway_url: Mutex<Option<Arc<RwLock<String>>>>,
}

/// Node connection status
pub struct NodeState {
    pub status: Mutex<String>,
}

/// File-based logger for macOS GUI apps (stdout not visible).
pub fn log(msg: &str) {
    use std::io::Write;
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open("/tmp/isol8-desktop.log") {
        let _ = writeln!(f, "{}", msg);
    }
    println!("{}", msg);
}

/// Called by the web app to send the Clerk JWT to the Rust backend.
/// Starts the node-host connection directly to the gateway.
#[tauri::command]
fn send_auth_token(
    token: String,
    display_name: String,
    user_id: String,
    state: State<'_, AuthState>,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let mut t = state.token.lock().map_err(|e| e.to_string())?;
    let is_first = t.is_none();
    *t = Some(token.clone());
    log(&format!("[auth] Received JWT ({} chars) for user {} ({})", token.len(), display_name, user_id));

    let ws_url = option_env!("ISOL8_WS_URL").unwrap_or("wss://ws-dev.isol8.co");
    let new_gateway_url = format!("{}?token={}", ws_url, token);

    // Rotate the running client's URL so the next reconnect uses the fresh
    // token. Clerk refreshes JWTs well before expiry, so we want every update
    // to propagate — not just the first one.
    if !is_first {
        if let Ok(handle_guard) = state.gateway_url.lock() {
            if let Some(handle) = handle_guard.as_ref() {
                if let Ok(mut url) = handle.write() {
                    *url = new_gateway_url;
                    log("[auth] Rotated node client URL with fresh token");
                }
            }
        }
        return Ok(());
    }

    // First token — create the shared URL handle, stash it in state, and spawn
    // the node client.
    let shared_url = Arc::new(RwLock::new(new_gateway_url));
    if let Ok(mut handle_guard) = state.gateway_url.lock() {
        *handle_guard = Some(shared_url.clone());
    }

    let app_handle = app.clone();
    tauri::async_runtime::spawn(async move {
        if let Err(e) = start_node_host(&app_handle, shared_url, &display_name).await {
            log(&format!("[node] Failed to start: {}", e));
            update_node_status(&app_handle, "error");
        }
    });

    Ok(())
}

async fn start_node_host(
    app: &tauri::AppHandle,
    gateway_url: Arc<RwLock<String>>,
    display_name: &str,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    update_node_status(app, "connecting");

    log("[node] Starting node client");
    let mut client = node_client::NodeClient::with_shared_url(gateway_url, display_name);
    let mut invoke_rx = client.start().await?;

    update_node_status(app, "connected");
    log("[node] Node client started, listening for invoke requests");

    tokio::spawn(async move {
        while let Some(request) = invoke_rx.recv().await {
            log(&format!("[node] Invoke: {} ({})", request.command, request.id));
            node_invoke::handle_invoke(&client, request).await;
        }
        log("[node] Invoke receiver closed");
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
            gateway_url: Mutex::new(None),
        })
        .manage(NodeState {
            status: Mutex::new("disconnected".into()),
        })
        .invoke_handler(tauri::generate_handler![
            send_auth_token,
            is_desktop,
            get_node_status,
        ])
        .setup(|app| {
            log("[setup] Isol8 desktop app starting");
            tray::create_tray(app.handle())?;

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
