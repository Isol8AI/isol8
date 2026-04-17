//! Node invoke handler — executes local commands on the user's Mac.
//!
//! Ported from OpenClaw's node-host invoke handlers:
//! - src/node-host/invoke.ts (dispatch + result building)
//! - src/node-host/invoke-system-run.ts (process spawning)

use crate::exec_approvals::{self, ApprovalDecision, ExecSecurity};
use crate::node_client::{InvokeError, NodeClient, NodeInvokeRequest, NodeInvokeResult};
use serde::Deserialize;
use std::collections::HashMap;
use std::path::Path;
use tokio::process::Command;

/// Max output size per stream (stdout/stderr) — 200KB, same as OpenClaw
const OUTPUT_CAP: usize = 200 * 1024;

#[derive(Deserialize)]
struct SystemRunParams {
    // OpenClaw's agent passes argv as `command: string[]`; see
    // openclaw/src/node-host/invoke-types.ts:3-17 and the caller at
    // openclaw/src/agents/bash-tools.exec-host-node.ts:107. Keep the Rust
    // field name short but alias on the wire.
    #[serde(rename = "command")]
    argv: Vec<String>,
    cwd: Option<String>,
    env: Option<HashMap<String, String>>,
    #[serde(rename = "timeoutMs")]
    timeout_ms: Option<u64>,
    input: Option<String>,
}

#[derive(Deserialize)]
struct WhichParams {
    // OpenClaw's SystemWhichParams uses `bins: string[]`; see
    // openclaw/src/node-host/invoke.ts:53-55.
    #[serde(rename = "bins")]
    names: Vec<String>,
}

/// Dispatch a node.invoke.request to the appropriate handler.
pub async fn handle_invoke(client: &NodeClient, request: NodeInvokeRequest) {
    let id = request.id.clone();
    let node_id = request.node_id.clone();
    let command = request.command.clone();

    let result = match command.as_str() {
        "system.run" => handle_system_run(&request).await,
        "system.run.prepare" => handle_system_run_prepare(&request).await,
        "system.which" => handle_system_which(&request).await,
        "system.execApprovals.get" => Ok(NodeInvokeResult {
            id,
            node_id,
            ok: true,
            payload_json: Some(exec_approvals::get_snapshot()),
            error: None,
        }),
        "system.execApprovals.set" => Ok(NodeInvokeResult {
            id,
            node_id,
            ok: true,
            payload_json: Some(r#"{"ok":true}"#.into()),
            error: None,
        }),
        _ => Ok(NodeInvokeResult {
            id,
            node_id,
            ok: false,
            payload_json: None,
            error: Some(InvokeError {
                code: "UNAVAILABLE".into(),
                message: format!("Unknown command: {}", command),
            }),
        }),
    };

    match result {
        Ok(invoke_result) => {
            if let Err(e) = client.send_invoke_result(invoke_result).await {
                eprintln!("[node-invoke] Failed to send result: {}", e);
            }
        }
        Err(e) => {
            let _ = client
                .send_invoke_result(NodeInvokeResult {
                    id: request.id.clone(),
                    node_id: request.node_id.clone(),
                    ok: false,
                    payload_json: None,
                    error: Some(InvokeError {
                        code: "INTERNAL".into(),
                        message: e.to_string(),
                    }),
                })
                .await;
        }
    }
}

async fn handle_system_run(
    request: &NodeInvokeRequest,
) -> Result<NodeInvokeResult, Box<dyn std::error::Error + Send + Sync>> {
    let params: SystemRunParams = parse_params(&request.params_json)?;

    if params.argv.is_empty() {
        return Ok(error_result(request, "INVALID_PARAMS", "argv is required"));
    }

    // Resolve argv[0] to an absolute path BEFORE approval checks. The
    // approval store keys on argv[0] — keying on a bare name like "git"
    // would let a binary placed earlier on PATH (e.g. /tmp/evil/git)
    // inherit a prior "Allow Always" approval for /usr/bin/git. Resolving
    // first binds approvals to the specific binary that will actually run,
    // and we spawn against the same resolved path (no re-resolution race).
    let argv = resolve_argv0_absolute(&params.argv).await;

    // Check exec approval before running
    let security = ExecSecurity::Allowlist; // Default security level
    match exec_approvals::check_approval(&argv, &security) {
        Ok(()) => {} // Approved — continue
        Err(reason) if reason.starts_with("APPROVAL_REQUIRED:") => {
            // Need user approval — show a native dialog
            let cmd_preview = argv.join(" ");
            let decision = prompt_exec_approval(&cmd_preview).await;
            match decision {
                ApprovalDecision::AllowOnce => {
                    // Continue execution this time only
                }
                ApprovalDecision::AllowAlways => {
                    exec_approvals::record_decision(&argv, ApprovalDecision::AllowAlways);
                }
                ApprovalDecision::Deny => {
                    exec_approvals::record_decision(&argv, ApprovalDecision::Deny);
                    return Ok(error_result(
                        request,
                        "EXEC_DENIED",
                        &format!("User denied execution of: {}", cmd_preview),
                    ));
                }
            }
        }
        Err(reason) => {
            return Ok(error_result(request, "EXEC_DENIED", &reason));
        }
    }

    let (cmd, args) = argv.split_first().unwrap();
    let cwd = params.cwd.unwrap_or_else(|| {
        std::env::var("HOME").unwrap_or_else(|_| "/tmp".into())
    });

    let mut command = Command::new(cmd);
    command.args(args).current_dir(&cwd);

    // Put the child in its own process group so a timeout-kill can take down
    // its entire subtree (e.g. `bash -c "sleep 999"` spawns `sleep` as a
    // child of bash; killing bash alone leaves sleep running and still
    // holding stdout/stderr open, which would make our drain tasks block
    // on EOF and break timeoutMs). `.process_group(0)` sets pgid = pid.
    // Note: tokio::process::Command exposes this directly under cfg(unix);
    // no trait import needed.
    #[cfg(unix)]
    command.process_group(0);

    // Sanitize environment
    let mut env = sanitize_env();
    if let Some(extra) = params.env {
        env.extend(extra);
    }
    command.envs(env);

    // Handle stdin
    command.stdin(std::process::Stdio::piped());
    command.stdout(std::process::Stdio::piped());
    command.stderr(std::process::Stdio::piped());

    let mut child = command.spawn()?;
    #[cfg(unix)]
    let child_pid: Option<i32> = child.id().map(|p| p as i32);

    // Write stdin if provided
    if let Some(input) = &params.input {
        if let Some(mut stdin) = child.stdin.take() {
            use tokio::io::AsyncWriteExt;
            let _ = stdin.write_all(input.as_bytes()).await;
            drop(stdin);
        }
    } else {
        drop(child.stdin.take());
    }

    // Take stdout/stderr handles so we can drain them concurrently with the
    // wait, and still collect (partial) output if we have to kill the child
    // on timeout.
    //
    // Memory safety: we cap what we STORE at OUTPUT_CAP but keep reading past
    // it so the child's pipe buffers don't fill and block it. A `yes` or
    // `cat /dev/urandom` used to buffer gigabytes in the Vec before truncation
    // and crash the desktop app (panic=abort in release).
    let stdout_pipe = child.stdout.take();
    let stderr_pipe = child.stderr.take();
    let stdout_task = tokio::spawn(async move { drain_with_cap(stdout_pipe).await });
    let stderr_task = tokio::spawn(async move { drain_with_cap(stderr_pipe).await });

    // Wait for exit, with optional timeout. On timeout, kill the whole
    // process GROUP — child.kill() only signals the direct pid, which for
    // wrapper commands like `bash -c "sleep 999"` leaves the grandchild
    // alive (and holding stdout/stderr, blocking the drain tasks).
    let (exit_status, timed_out) = if let Some(timeout_ms) = params.timeout_ms {
        match tokio::time::timeout(
            std::time::Duration::from_millis(timeout_ms),
            child.wait(),
        )
        .await
        {
            Ok(status) => (status?, false),
            Err(_) => {
                #[cfg(unix)]
                {
                    if let Some(pid) = child_pid {
                        // killpg(pgid, SIGKILL). Safe because we set
                        // process_group(0) at spawn time — pgid == pid.
                        unsafe {
                            libc::killpg(pid, libc::SIGKILL);
                        }
                    }
                }
                // Still call child.kill() for correctness on non-unix and
                // to reap the direct child's zombie. On unix the pgroup
                // signal already delivered SIGKILL to it.
                let _ = child.kill().await;
                let status = child.wait().await.unwrap_or_default();
                (status, true)
            }
        }
    } else {
        (child.wait().await?, false)
    };

    let stdout_bytes = stdout_task.await.unwrap_or_default();
    let mut stderr_bytes = stderr_task.await.unwrap_or_default();
    if timed_out && stderr_bytes.is_empty() {
        stderr_bytes = b"Process timed out".to_vec();
    }
    let output = std::process::Output {
        status: exit_status,
        stdout: stdout_bytes,
        stderr: stderr_bytes,
    };

    let stdout = truncate_output(&output.stdout);
    let stderr = truncate_output(&output.stderr);
    let exit_code = output.status.code();
    // OpenClaw's RunResult.success is `exitCode === 0 && !timedOut && !error`
    // (openclaw/src/node-host/invoke.ts:268). Spawn errors would have returned
    // earlier with ok:false, so we just check exit + timeout here. The agent
    // reads this field directly (bash-tools.exec-host-node.ts:443,453) and
    // marks any run missing it or with false as failed.
    let success = exit_code == Some(0) && !timed_out;

    let payload = serde_json::json!({
        "exitCode": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timedOut": timed_out,
        "success": success,
        "error": null,
    });

    Ok(NodeInvokeResult {
        id: request.id.clone(),
        node_id: request.node_id.clone(),
        ok: true,
        payload_json: Some(payload.to_string()),
        error: None,
    })
}

async fn handle_system_run_prepare(
    request: &NodeInvokeRequest,
) -> Result<NodeInvokeResult, Box<dyn std::error::Error + Send + Sync>> {
    let params: SystemRunParams = parse_params(&request.params_json)?;

    if params.argv.is_empty() {
        return Ok(error_result(request, "INVALID_PARAMS", "argv is required"));
    }

    // Resolve argv[0] so the approval check uses the same path-keyed lookup
    // system.run will use. If we checked with a bare name and system.run
    // later resolved to a different absolute path, approved=true here and
    // EXEC_DENIED there would be inconsistent.
    let argv = resolve_argv0_absolute(&params.argv).await;

    // Mirror the approval policy system.run will apply, WITHOUT prompting —
    // prepare must report truthful approval state so the agent doesn't call
    // system.run on something that will then be denied. Showing a dialog
    // here would produce two prompts for one command.
    let security = ExecSecurity::Allowlist;
    let would_be_approved = exec_approvals::check_approval(&argv, &security).is_ok();

    // resolvedPath matches what system.run would actually execute.
    let resolved: Option<String> = if std::path::Path::new(&argv[0]).is_absolute() {
        Some(argv[0].clone())
    } else {
        None
    };
    let payload = serde_json::json!({
        "approved": would_be_approved && resolved.is_some(),
        "resolvedPath": resolved,
    });

    Ok(NodeInvokeResult {
        id: request.id.clone(),
        node_id: request.node_id.clone(),
        ok: true,
        payload_json: Some(payload.to_string()),
        error: None,
    })
}

async fn handle_system_which(
    request: &NodeInvokeRequest,
) -> Result<NodeInvokeResult, Box<dyn std::error::Error + Send + Sync>> {
    let params: WhichParams = parse_params(&request.params_json)?;

    // Match OpenClaw's shape: { bins: { name: path } } containing ONLY the
    // names that resolved. See openclaw/src/node-host/invoke.ts:316-326.
    let mut found: HashMap<String, String> = HashMap::new();
    for name in &params.names {
        let trimmed = name.trim();
        if trimmed.is_empty() {
            continue;
        }
        if let Some(path) = which(trimmed).await {
            found.insert(trimmed.to_string(), path);
        }
    }

    let payload = serde_json::json!({ "bins": found });
    Ok(NodeInvokeResult {
        id: request.id.clone(),
        node_id: request.node_id.clone(),
        ok: true,
        payload_json: Some(payload.to_string()),
        error: None,
    })
}

// --- Exec approval prompt ---

/// Show a native macOS dialog asking the user to approve command execution.
/// Returns the user's decision.
async fn prompt_exec_approval(command_preview: &str) -> ApprovalDecision {
    // Use osascript to show a native dialog with three buttons.
    // This runs on the main thread and blocks until the user responds.
    let script = format!(
        r#"display dialog "Isol8 agent wants to run:\n\n{}" with title "Isol8 - Command Approval" buttons {{"Deny", "Allow Once", "Allow Always"}} default button "Allow Once" with icon caution"#,
        command_preview.replace('"', r#"\""#).replace('\n', r#"\n"#)
    );

    let output = tokio::process::Command::new("osascript")
        .arg("-e")
        .arg(&script)
        .output()
        .await;

    match output {
        Ok(out) => {
            let stdout = String::from_utf8_lossy(&out.stdout);
            if stdout.contains("Allow Always") {
                ApprovalDecision::AllowAlways
            } else if stdout.contains("Allow Once") {
                ApprovalDecision::AllowOnce
            } else {
                ApprovalDecision::Deny
            }
        }
        Err(_) => {
            // Dialog failed to show — deny by default
            ApprovalDecision::Deny
        }
    }
}

// --- Helpers ---

async fn which(name: &str) -> Option<String> {
    if Path::new(name).is_absolute() {
        if is_executable(name).await {
            return Some(name.into());
        }
        return None;
    }

    let path_var = std::env::var("PATH").unwrap_or_default();
    for dir in path_var.split(':') {
        let full_path = format!("{}/{}", dir, name);
        if is_executable(&full_path).await {
            return Some(full_path);
        }
    }
    None
}

/// Resolve argv[0] to an absolute path via PATH, returning a new argv where
/// argv[0] is the resolved path if one was found. This is the pre-approval-
/// check normalization that binds approvals to a specific binary rather than
/// a basename that PATH lookup could alias onto a malicious file. If
/// resolution fails (binary not on PATH) the original argv is returned
/// unchanged — the approval check and subsequent spawn will both reject it
/// on their own.
async fn resolve_argv0_absolute(argv: &[String]) -> Vec<String> {
    if argv.is_empty() {
        return argv.to_vec();
    }
    let mut out = argv.to_vec();
    if let Some(resolved) = which(&argv[0]).await {
        out[0] = resolved;
    }
    out
}

async fn is_executable(path: &str) -> bool {
    use std::os::unix::fs::PermissionsExt;
    tokio::fs::metadata(path)
        .await
        .map(|m| m.permissions().mode() & 0o111 != 0)
        .unwrap_or(false)
}

fn parse_params<T: serde::de::DeserializeOwned>(
    params_json: &Option<String>,
) -> Result<T, Box<dyn std::error::Error + Send + Sync>> {
    match params_json {
        Some(json) => Ok(serde_json::from_str(json)?),
        None => Err("Missing params".into()),
    }
}

fn truncate_output(bytes: &[u8]) -> String {
    // Cap on bytes (not chars) and convert via from_utf8_lossy so a boundary
    // landing mid-codepoint becomes a replacement char instead of a panic
    // (release builds use panic = "abort", so this would crash the app).
    let slice = if bytes.len() > OUTPUT_CAP {
        &bytes[..OUTPUT_CAP]
    } else {
        bytes
    };
    String::from_utf8_lossy(slice).into_owned()
}

/// Drain a child stdio pipe, keeping at most OUTPUT_CAP bytes in memory.
/// Excess is read and discarded so the pipe doesn't back-pressure the child —
/// otherwise a high-volume writer (yes, cat /dev/urandom) would either block
/// forever or we'd have to kill the child to stop it. We also need the cap
/// enforced *during* reads so we don't OOM before truncation.
async fn drain_with_cap<R>(pipe: Option<R>) -> Vec<u8>
where
    R: tokio::io::AsyncRead + Unpin,
{
    use tokio::io::AsyncReadExt;
    let mut buf = Vec::with_capacity(4096);
    let Some(mut pipe) = pipe else { return buf };
    let mut chunk = [0u8; 8 * 1024];
    loop {
        match pipe.read(&mut chunk).await {
            Ok(0) => break, // EOF
            Ok(n) => {
                if buf.len() < OUTPUT_CAP {
                    let remaining = OUTPUT_CAP - buf.len();
                    let take = n.min(remaining);
                    buf.extend_from_slice(&chunk[..take]);
                }
                // Past the cap: discard rest of this chunk (and future chunks),
                // but keep draining so the child's pipe buffer doesn't fill.
            }
            Err(_) => break,
        }
    }
    buf
}

fn sanitize_env() -> HashMap<String, String> {
    let mut env: HashMap<String, String> = std::env::vars().collect();
    // Remove sensitive Tauri/Node internals
    env.remove("ELECTRON_RUN_AS_NODE");
    env.remove("NODE_OPTIONS");
    env.remove("TAURI_ENV_DEBUG");
    env
}

fn error_result(request: &NodeInvokeRequest, code: &str, message: &str) -> NodeInvokeResult {
    NodeInvokeResult {
        id: request.id.clone(),
        node_id: request.node_id.clone(),
        ok: false,
        payload_json: None,
        error: Some(InvokeError {
            code: code.into(),
            message: message.into(),
        }),
    }
}
