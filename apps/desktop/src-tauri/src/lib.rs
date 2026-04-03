mod tray;

use std::sync::Mutex;
use tauri::{Emitter, Manager, State, Url};
use tauri_plugin_deep_link::DeepLinkExt;

/// Shared auth token state
pub struct AuthState {
    pub token: Mutex<Option<String>>,
}

/// Node connection status
pub struct NodeState {
    pub status: Mutex<String>,
}

/// Called by the web app to send the Clerk JWT to the Rust backend.
#[tauri::command]
fn send_auth_token(
    token: String,
    state: State<'_, AuthState>,
    _app: tauri::AppHandle,
) -> Result<(), String> {
    let mut t = state.token.lock().map_err(|e| e.to_string())?;
    *t = Some(token.clone());

    // TODO (Phase 2): Start the node client here
    println!("[auth] Received Clerk JWT ({} chars)", token.len());

    Ok(())
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
/// WKWebView cannot access passkeys for third-party domains (Apple restriction).
const OAUTH_DOMAINS: &[&str] = &["accounts.google.com", "appleid.apple.com"];

/// Sign-in URL that redirects to the desktop callback after auth.
/// The callback page gets the Clerk token and redirects to isol8://auth?token=...
const DESKTOP_SIGNIN_URL: &str = "https://dev.isol8.co/sign-in?redirect_url=%2Fauth%2Fdesktop-callback&x-vercel-protection-bypass=BWitr6v05GtUmGWJsjlfkqrOGyb68tR8&x-vercel-set-bypass-cookie=samesitenone";

fn is_oauth_url(url: &Url) -> bool {
    let host = url.host_str().unwrap_or("");
    OAUTH_DOMAINS.iter().any(|d| host == *d || host.ends_with(&format!(".{}", d)))
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(
            // Intercept OAuth navigations → open in system browser where
            // passkeys/Touch ID work. WKWebView cannot access passkeys for
            // third-party domains (hard Apple platform restriction).
            tauri::plugin::Builder::<tauri::Wry>::new("oauth-intercept")
                .on_navigation(|_window, url| {
                    if is_oauth_url(url) {
                        let _ = open::that(DESKTOP_SIGNIN_URL);
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
        })
        .invoke_handler(tauri::generate_handler![
            send_auth_token,
            is_desktop,
            get_node_status,
        ])
        .setup(|app| {
            // Create system tray
            tray::create_tray(app.handle())?;

            // Handle deep links (isol8:// protocol)
            let app_handle = app.handle().clone();
            app.deep_link().on_open_url(move |event| {
                let urls = event.urls();
                for url_obj in urls {
                    let url_str = url_obj.to_string();
                    if url_str.starts_with("isol8://auth") {
                        if let Ok(parsed) = url::Url::parse(&url_str) {
                            // Look for the sign-in ticket from the desktop callback
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

                    // Bring window to front
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
