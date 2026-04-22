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
        // A stored Child is not proof of life — a crashed subprocess
        // leaves the handle `Some` even though the process is gone.
        // Probe try_wait() and clear the slot so the next block respawns.
        if let Some(existing) = guard.as_mut() {
            match existing.try_wait() {
                Ok(None) => return Ok(()), // still running
                Ok(Some(status)) => {
                    crate::log(&format!(
                        "[browser-sidecar] previous child exited ({status}); respawning"
                    ));
                    *guard = None;
                }
                Err(e) => {
                    crate::log(&format!(
                        "[browser-sidecar] try_wait failed ({e}); respawning"
                    ));
                    *guard = None;
                }
            }
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
    /// Production constructor: resolves the externalBin sidecar path.
    /// Tauri places externalBin binaries next to the main executable
    /// (not in Resources/) with a `-<target-triple>` suffix — mirror
    /// that resolution here. Works for both dev (`target/debug/`) and
    /// packaged builds (`Isol8.app/Contents/MacOS/`).
    ///
    /// We ship a universal-apple-darwin dispatch shim (a bash script
    /// that picks node-<arch> + openclaw-host-<arch> at runtime via
    /// uname -m), so this always resolves the same filename regardless
    /// of the slice the loader selected.
    pub fn for_app(_app: &tauri::AppHandle) -> Result<Self, String> {
        let exe = std::env::current_exe()
            .map_err(|e| format!("current_exe: {}", e))?;
        let parent = exe
            .parent()
            .ok_or_else(|| "current_exe has no parent".to_string())?;
        let triple = current_sidecar_triple()?;
        let binary = parent.join(format!("isol8-browser-service-{}", triple));
        if !binary.exists() {
            return Err(format!(
                "sidecar binary not found at {} (arch={})",
                binary.display(),
                std::env::consts::ARCH,
            ));
        }
        Ok(Self {
            binary,
            args: vec![],
            child: std::sync::Arc::new(tokio::sync::Mutex::new(None)),
        })
    }
}

/// Sidecar filename suffix for the running binary's arch. We ship
/// per-arch DMGs (aarch64 + x86_64), so `std::env::consts::ARCH`
/// reflects the arch of THIS compiled binary — matches the one
/// tauri-bundler copied next to the main executable.
fn current_sidecar_triple() -> Result<String, String> {
    match std::env::consts::ARCH {
        "aarch64" => Ok("aarch64-apple-darwin".into()),
        "x86_64" => Ok("x86_64-apple-darwin".into()),
        other => Err(format!("unsupported sidecar arch: {}", other)),
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
