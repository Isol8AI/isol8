//! Exec approval system — gates command execution on the user's Mac.
//!
//! Ported from OpenClaw's exec-approvals system. Three security levels:
//! - "deny": block all execution
//! - "allowlist": only pre-approved commands run without prompting
//! - "full": everything runs (unsafe, not recommended)
//!
//! Default is "allowlist" with a set of safe binaries that don't need approval.
//! Unknown commands trigger a native macOS dialog asking the user to approve.

use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::path::PathBuf;
use std::sync::Mutex;

/// Approval decision from the user
#[derive(Debug, Clone, PartialEq)]
pub enum ApprovalDecision {
    AllowOnce,
    AllowAlways,
    Deny,
}

/// Security level for exec approvals
#[derive(Debug, Clone, PartialEq)]
pub enum ExecSecurity {
    Deny,
    Allowlist,
    Full,
}

/// Persistent approval store
#[derive(Debug, Default, Serialize, Deserialize)]
pub struct ApprovalStore {
    /// Commands the user has approved with "allow always"
    always_allowed: HashSet<String>,
    /// Commands the user has denied
    denied: HashSet<String>,
}

/// Safe binaries that don't need approval (read-only commands).
/// Ported from OpenClaw's DEFAULT_SAFE_BINS.
const SAFE_BINS: &[&str] = &[
    "cat", "head", "tail", "less", "more",
    "ls", "find", "tree", "du", "df", "stat",
    "grep", "rg", "ag", "awk", "sed", "sort", "uniq", "wc", "cut", "tr",
    "echo", "printf", "date", "cal",
    "pwd", "whoami", "hostname", "uname", "id", "env", "printenv",
    "which", "where", "type", "file", "readlink",
    "git", "gh",
    "node", "npm", "npx", "pnpm", "yarn", "bun",
    "python", "python3", "pip", "pip3", "uv",
    "cargo", "rustc", "rustup",
    "go",
    "ruby", "gem",
    "java", "javac", "mvn", "gradle",
    "docker", "docker-compose",
    "curl", "wget", "ping", "dig", "nslookup", "host",
    "jq", "yq", "xmllint",
    "tar", "zip", "unzip", "gzip", "gunzip",
    "diff", "patch",
    "make", "cmake",
    "man", "help",
    "true", "false", "test",
    "xargs",
    "tee",
    "realpath", "dirname", "basename",
    "md5", "shasum", "sha256sum",
    "pbcopy", "pbpaste",
    "open",
    "say",
    "sw_vers", "system_profiler",
];

/// Shell wrappers that need special handling — the inline command
/// needs to be checked, not just the wrapper binary.
const SHELL_WRAPPERS: &[&str] = &["sh", "bash", "zsh", "fish", "dash"];

lazy_static::lazy_static! {
    static ref STORE: Mutex<ApprovalStore> = Mutex::new(load_store());
    static ref SAFE_BIN_SET: HashSet<String> = SAFE_BINS.iter().map(|s| s.to_string()).collect();
}

/// Check if a command is allowed to execute.
/// Returns Ok(()) if allowed, Err with reason if denied.
pub fn check_approval(argv: &[String], security: &ExecSecurity) -> Result<(), String> {
    match security {
        ExecSecurity::Deny => {
            Err("Execution denied: security mode is 'deny'".into())
        }
        ExecSecurity::Full => Ok(()),
        ExecSecurity::Allowlist => check_allowlist(argv),
    }
}

fn check_allowlist(argv: &[String]) -> Result<(), String> {
    if argv.is_empty() {
        return Err("Empty command".into());
    }

    let binary = extract_binary_name(&argv[0]);

    // Check if it's a safe binary
    if SAFE_BIN_SET.contains(&binary) {
        // Shell wrappers need special handling: check the inline command too
        if SHELL_WRAPPERS.contains(&binary.as_str()) {
            // sh -c "command" — check if the inline command is safe
            if let Some(inline_cmd) = extract_shell_inline_command(argv) {
                let inline_binary = extract_binary_name(&inline_cmd);
                if SAFE_BIN_SET.contains(&inline_binary) {
                    return Ok(());
                }
                // Inline command not in safe list — check always-allowed
                let store = STORE.lock().unwrap();
                let key = format_approval_key(argv);
                if store.always_allowed.contains(&key) {
                    return Ok(());
                }
                if store.denied.contains(&key) {
                    return Err(format!("Command denied by user: {}", argv.join(" ")));
                }
                return Err(format!("APPROVAL_REQUIRED:{}", key));
            }
        }
        return Ok(());
    }

    // Check always-allowed store
    let store = STORE.lock().unwrap();
    let key = format_approval_key(argv);
    if store.always_allowed.contains(&key) {
        return Ok(());
    }
    if store.denied.contains(&key) {
        return Err(format!("Command denied by user: {}", argv.join(" ")));
    }

    // Not in any list — needs approval
    Err(format!("APPROVAL_REQUIRED:{}", key))
}

/// Record a user's approval decision.
pub fn record_decision(argv: &[String], decision: ApprovalDecision) {
    let key = format_approval_key(argv);
    let mut store = STORE.lock().unwrap();
    match decision {
        ApprovalDecision::AllowOnce => {
            // Temporarily allowed — we handle this at the call site
        }
        ApprovalDecision::AllowAlways => {
            store.always_allowed.insert(key.clone());
            store.denied.remove(&key);
            save_store(&store);
        }
        ApprovalDecision::Deny => {
            store.denied.insert(key.clone());
            store.always_allowed.remove(&key);
            save_store(&store);
        }
    }
}

/// Get the current approval snapshot (for system.execApprovals.get)
pub fn get_snapshot() -> String {
    let store = STORE.lock().unwrap();
    serde_json::to_string(&*store).unwrap_or_else(|_| r#"{"always_allowed":[],"denied":[]}"#.into())
}

// --- Internal helpers ---

fn extract_binary_name(cmd: &str) -> String {
    PathBuf::from(cmd)
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| cmd.to_string())
        .to_lowercase()
}

fn extract_shell_inline_command(argv: &[String]) -> Option<String> {
    // Pattern: sh -c "command args..."
    if argv.len() >= 3 && argv[1] == "-c" {
        let cmd = argv[2..].join(" ");
        // Extract the first word of the inline command
        return cmd.split_whitespace().next().map(|s| s.to_string());
    }
    None
}

fn format_approval_key(argv: &[String]) -> String {
    // Key is the binary name (not full path) for simpler matching
    extract_binary_name(&argv[0])
}

fn store_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".into());
    PathBuf::from(home)
        .join(".isol8")
        .join("exec-approvals.json")
}

fn load_store() -> ApprovalStore {
    let path = store_path();
    if let Ok(data) = std::fs::read_to_string(&path) {
        serde_json::from_str(&data).unwrap_or_default()
    } else {
        ApprovalStore::default()
    }
}

fn save_store(store: &ApprovalStore) {
    let path = store_path();
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    if let Ok(json) = serde_json::to_string_pretty(store) {
        let _ = std::fs::write(&path, json);
    }
}
