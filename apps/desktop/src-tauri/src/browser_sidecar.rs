//! Subprocess supervisor for the OpenClaw node-host running on the
//! user's Mac. The launcher at bin/isol8-browser-service-<triple>
//! invokes `node openclaw.mjs node run --port 18789`, which serves
//! the browser control HTTP API on 18789+2 = 18791 (per
//! src/config/port-defaults.ts:deriveDefaultBrowserControlPort in
//! openclaw@v2026.4.5). Port is deterministic so we don't parse stdout.

use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::Mutex;

/// Gateway port we pass to `openclaw node run --port`. Must match
/// what the launcher shim in scripts/vendor-sidecars.sh sets.
pub const GATEWAY_PORT: u16 = 18789;

/// Browser control HTTP port. OpenClaw derives this as
/// `gatewayPort + 2` in src/config/port-defaults.ts. Pinning the
/// gateway port pins this.
pub const BROWSER_CONTROL_PORT: u16 = GATEWAY_PORT + 2;

pub struct BrowserSidecar {
    binary: PathBuf,
    args: Vec<String>,
    child: Arc<Mutex<Option<Child>>>,
}

impl BrowserSidecar {
    pub fn new_for_test(binary: PathBuf, args: Vec<String>) -> Self {
        Self {
            binary,
            args,
            child: Arc::new(Mutex::new(None)),
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

        if let Some(out) = child.stdout.take() {
            tokio::spawn(async move {
                let reader = BufReader::new(out);
                let mut lines = reader.lines();
                while let Ok(Some(line)) = lines.next_line().await {
                    crate::log(&format!("[browser-sidecar] {}", line));
                }
            });
        }
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

    pub fn port(&self) -> u16 {
        BROWSER_CONTROL_PORT
    }
}

impl BrowserSidecar {
    /// Production constructor: resolves the bundled sidecar binary
    /// path from Tauri's resource dir.
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
    use super::*;

    #[test]
    fn browser_port_derives_from_gateway() {
        assert_eq!(BROWSER_CONTROL_PORT, GATEWAY_PORT + 2);
    }
}
