//! Subprocess supervisor for the Node.js-based browser control service
//! (openclaw/extensions/browser/ + chrome-devtools-mcp). Spawned on
//! demand when the first browser.proxy RPC arrives; stays alive until
//! the app exits or the subprocess dies (in which case the next
//! browser.proxy call respawns it).

use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::Mutex;

#[derive(Debug)]
pub enum SidecarState {
    Stopped,
    Running { pid: Option<u32>, port: u16 },
}

pub struct BrowserSidecar {
    binary: PathBuf,
    args: Vec<String>,
    child: Arc<Mutex<Option<Child>>>,
    port: Arc<Mutex<u16>>,
}

impl BrowserSidecar {
    pub fn new_for_test(binary: PathBuf, args: Vec<String>) -> Self {
        Self {
            binary,
            args,
            child: Arc::new(Mutex::new(None)),
            port: Arc::new(Mutex::new(0)),
        }
    }

    pub async fn start(&self) -> Result<(), String> {
        let mut guard = self.child.lock().await;
        if guard.is_some() {
            return Ok(());
        }
        let mut child = Command::new(&self.binary)
            .args(&self.args)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| format!("spawn failed: {}", e))?;

        // Pipe stdout: parse for "listening on 127.0.0.1:<port>" and
        // forward every line to the file logger.
        if let Some(out) = child.stdout.take() {
            let port_slot = self.port.clone();
            tokio::spawn(async move {
                let reader = BufReader::new(out);
                let mut lines = reader.lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    crate::log(&format!("[browser-sidecar] {}", line));
                    if let Some(port) = parse_listening_port(&line) {
                        if let Ok(mut slot) = port_slot.try_lock() {
                            *slot = port;
                        }
                    }
                }
            });
        }
        // Pipe stderr: forward to log with a prefix.
        if let Some(err) = child.stderr.take() {
            tokio::spawn(async move {
                let reader = BufReader::new(err);
                let mut lines = reader.lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    crate::log(&format!("[browser-sidecar err] {}", line));
                }
            });
        }

        *guard = Some(child);
        Ok(())
    }

    pub async fn stop(&self) {
        let mut guard = self.child.lock().await;
        if let Some(mut c) = guard.take() {
            let _ = c.kill().await;
        }
        if let Ok(mut slot) = self.port.try_lock() {
            *slot = 0;
        }
    }

    pub fn state(&self) -> SidecarState {
        let child_present = self
            .child
            .try_lock()
            .map(|g| g.is_some())
            .unwrap_or(false);
        if child_present {
            let port = self.port.try_lock().map(|g| *g).unwrap_or(0);
            SidecarState::Running { pid: None, port }
        } else {
            SidecarState::Stopped
        }
    }

    pub async fn port(&self) -> Option<u16> {
        let p = *self.port.lock().await;
        if p == 0 {
            None
        } else {
            Some(p)
        }
    }
}

/// Parse "listening on 127.0.0.1:PORT" style lines. Accepts both
/// "listening on 127.0.0.1:54321" and "…http://127.0.0.1:54321/…"
/// so minor log-format drift in the upstream service doesn't break us.
fn parse_listening_port(line: &str) -> Option<u16> {
    let needle = "127.0.0.1:";
    let idx = line.find(needle)?;
    let rest = &line[idx + needle.len()..];
    let end = rest.find(|c: char| !c.is_ascii_digit()).unwrap_or(rest.len());
    rest[..end].parse().ok()
}

impl BrowserSidecar {
    /// Production constructor: resolves the bundled sidecar binary
    /// path from Tauri's resource dir. Call from a Tauri context
    /// where AppHandle is available.
    pub fn for_app(app: &tauri::AppHandle) -> Result<Self, String> {
        use tauri::Manager;
        let sidecar = app
            .path()
            .resolve(
                "isol8-browser-service",
                tauri::path::BaseDirectory::Resource,
            )
            .map_err(|e| format!("resolve sidecar path: {}", e))?;
        Ok(Self {
            binary: sidecar,
            args: vec![],
            child: std::sync::Arc::new(tokio::sync::Mutex::new(None)),
            port: std::sync::Arc::new(tokio::sync::Mutex::new(0)),
        })
    }
}

/// Shared-state handle passed through Tauri's `.manage()`. The inner
/// Option is None until the first browser.proxy invoke spawns the
/// sidecar.
pub type BrowserSidecarHandle =
    std::sync::Arc<tokio::sync::RwLock<Option<BrowserSidecar>>>;

#[cfg(test)]
mod tests {
    use super::parse_listening_port;

    #[test]
    fn parses_plain_form() {
        assert_eq!(parse_listening_port("listening on 127.0.0.1:54321"), Some(54321));
    }

    #[test]
    fn parses_url_form() {
        assert_eq!(
            parse_listening_port("[info] http://127.0.0.1:18791/ ready"),
            Some(18791)
        );
    }

    #[test]
    fn ignores_unrelated_lines() {
        assert_eq!(parse_listening_port("starting chrome-devtools-mcp"), None);
    }
}
