use isol8_desktop::browser_sidecar::{BrowserSidecar, SidecarState};
use std::path::PathBuf;

#[tokio::test]
async fn spawn_fake_binary_reports_ready() {
    // Use `/bin/sh -c "sleep 3600"` as a stand-in for the real sidecar
    // so the test doesn't require Node.js / vendored bundle to pass.
    let sidecar = BrowserSidecar::new_for_test(
        PathBuf::from("/bin/sh"),
        vec!["-c".into(), "sleep 3600".into()],
    );
    sidecar.start().await.expect("spawn");
    assert!(matches!(sidecar.state(), SidecarState::Running { .. }));
    sidecar.stop().await;
    assert!(matches!(sidecar.state(), SidecarState::Stopped));
}

#[tokio::test]
async fn start_is_idempotent() {
    let sidecar = BrowserSidecar::new_for_test(
        PathBuf::from("/bin/sh"),
        vec!["-c".into(), "sleep 3600".into()],
    );
    sidecar.start().await.expect("first spawn");
    sidecar.start().await.expect("second call is a no-op");
    sidecar.stop().await;
}
