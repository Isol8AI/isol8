use isol8_desktop::browser_sidecar::{BrowserSidecar, BROWSER_CONTROL_PORT, GATEWAY_PORT};
use std::path::PathBuf;

#[tokio::test]
async fn spawn_fake_binary_runs() {
    // Use `/bin/sh -c "sleep 3600"` as a stand-in for the real
    // sidecar so the test doesn't require the vendored bundle.
    let sidecar = BrowserSidecar::new_for_test(
        PathBuf::from("/bin/sh"),
        vec!["-c".into(), "sleep 3600".into()],
    );
    sidecar.start().await.expect("spawn");
    // Port is deterministic — no stdout parsing required.
    assert_eq!(sidecar.port(), BROWSER_CONTROL_PORT);
}

#[tokio::test]
async fn start_is_idempotent() {
    let sidecar = BrowserSidecar::new_for_test(
        PathBuf::from("/bin/sh"),
        vec!["-c".into(), "sleep 3600".into()],
    );
    sidecar.start().await.expect("first spawn");
    sidecar.start().await.expect("second call is a no-op");
}

#[tokio::test]
async fn start_respawns_after_child_exits() {
    // Child that exits immediately. Without the try_wait() probe in
    // start(), the stale `Child` handle would linger as Some and
    // subsequent calls would become no-ops — the bug Codex flagged.
    let sidecar = BrowserSidecar::new_for_test(
        PathBuf::from("/bin/sh"),
        vec!["-c".into(), "exit 0".into()],
    );
    sidecar.start().await.expect("first spawn");
    // Give the process a moment to exit.
    tokio::time::sleep(std::time::Duration::from_millis(100)).await;
    // Calling start() again must detect the dead child and respawn.
    sidecar.start().await.expect("second spawn after exit");
}

#[test]
fn port_matches_openclaw_derivation() {
    // OpenClaw src/config/port-defaults.ts:
    //   deriveDefaultBrowserControlPort(gatewayPort) = gatewayPort + 2
    assert_eq!(BROWSER_CONTROL_PORT, GATEWAY_PORT + 2);
}
