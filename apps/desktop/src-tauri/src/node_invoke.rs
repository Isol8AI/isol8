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
    argv: Vec<String>,
    cwd: Option<String>,
    env: Option<HashMap<String, String>>,
    #[serde(rename = "timeoutMs")]
    timeout_ms: Option<u64>,
    input: Option<String>,
}

#[derive(Deserialize)]
struct WhichParams {
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

    // Check exec approval before running
    let security = ExecSecurity::Allowlist; // Default security level
    match exec_approvals::check_approval(&params.argv, &security) {
        Ok(()) => {} // Approved — continue
        Err(reason) if reason.starts_with("APPROVAL_REQUIRED:") => {
            // Need user approval — show a native dialog
            let cmd_preview = params.argv.join(" ");
            let decision = prompt_exec_approval(&cmd_preview).await;
            match decision {
                ApprovalDecision::AllowOnce => {
                    // Continue execution this time only
                }
                ApprovalDecision::AllowAlways => {
                    exec_approvals::record_decision(&params.argv, ApprovalDecision::AllowAlways);
                }
                ApprovalDecision::Deny => {
                    exec_approvals::record_decision(&params.argv, ApprovalDecision::Deny);
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

    let (cmd, args) = params.argv.split_first().unwrap();
    let cwd = params.cwd.unwrap_or_else(|| {
        std::env::var("HOME").unwrap_or_else(|_| "/tmp".into())
    });

    let mut command = Command::new(cmd);
    command.args(args).current_dir(&cwd);

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

    // Wait with timeout
    let timed_out;
    let output = if let Some(timeout_ms) = params.timeout_ms {
        match tokio::time::timeout(
            std::time::Duration::from_millis(timeout_ms),
            child.wait_with_output(),
        )
        .await
        {
            Ok(result) => {
                timed_out = false;
                result?
            }
            Err(_) => {
                // Timeout — we can't kill the child since wait_with_output consumed it.
                // The future was dropped which should clean up the process.
                timed_out = true;
                std::process::Output {
                    status: std::process::ExitStatus::default(),
                    stdout: Vec::new(),
                    stderr: b"Process timed out".to_vec(),
                }
            }
        }
    } else {
        timed_out = false;
        child.wait_with_output().await?
    };

    let stdout = truncate_output(&output.stdout);
    let stderr = truncate_output(&output.stderr);
    let exit_code = output.status.code();

    let payload = serde_json::json!({
        "exitCode": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timedOut": timed_out,
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

    let resolved = which(&params.argv[0]).await;
    let payload = serde_json::json!({
        "approved": resolved.is_some(),
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

    let mut results = HashMap::new();
    for name in &params.names {
        results.insert(name.clone(), which(name).await);
    }

    Ok(NodeInvokeResult {
        id: request.id.clone(),
        node_id: request.node_id.clone(),
        ok: true,
        payload_json: Some(serde_json::to_string(&results)?),
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
    let s = String::from_utf8_lossy(bytes);
    if s.len() > OUTPUT_CAP {
        s[..OUTPUT_CAP].to_string()
    } else {
        s.into_owned()
    }
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
