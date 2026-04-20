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

#[test]
fn port_matches_openclaw_derivation() {
    // OpenClaw src/config/port-defaults.ts:
    //   deriveDefaultBrowserControlPort(gatewayPort) = gatewayPort + 2
    assert_eq!(BROWSER_CONTROL_PORT, GATEWAY_PORT + 2);
}
