//! Subprocess supervisor for the Node.js-based browser control service
//! (openclaw/extensions/browser/ + chrome-devtools-mcp). Spawned on
//! demand when the first browser.proxy RPC arrives; stays alive until
//! the app exits or the subprocess dies (in which case the next
//! browser.proxy call respawns it).

use std::path::PathBuf;
use std::sync::Arc;
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
    /// Constructor for tests — lets us swap the binary path without
    /// forcing the real sidecar to be built.
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
            return Ok(()); // already running
        }
        let child = Command::new(&self.binary)
            .args(&self.args)
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| format!("spawn failed: {}", e))?;
        *guard = Some(child);
        // Placeholder: real impl (Task 6) will parse stdout for "listening
        // on port N" and populate self.port. Tests pass with 0 for now.
        Ok(())
    }

    pub async fn stop(&self) {
        let mut guard = self.child.lock().await;
        if let Some(mut c) = guard.take() {
            let _ = c.kill().await;
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
}
