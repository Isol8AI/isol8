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

/// Binaries that can execute arbitrary inline code via a flag. When invoked
/// this way, the PAYLOAD is the real instruction — approving `bash` once
/// must NOT grant a blanket allow for every future `bash -c <anything>`.
/// The approval key for these includes the inline payload (see
/// `approval_key_for`), so each distinct inline command prompts separately.
///
/// `(binary, flags_that_take_inline_code)`
const INLINE_CODE_WRAPPERS: &[(&str, &[&str])] = &[
    ("sh", &["-c"]),
    ("bash", &["-c"]),
    ("zsh", &["-c"]),
    ("fish", &["-c"]),
    ("dash", &["-c"]),
    ("ksh", &["-c"]),
    ("python", &["-c"]),
    ("python3", &["-c"]),
    ("python2", &["-c"]),
    ("node", &["-e", "--eval", "-p", "--print"]),
    ("ruby", &["-e"]),
    ("perl", &["-e", "-E"]),
];

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

    // Inline-code invocations (e.g. `bash -c ...`, `python -c ...`, `node -e ...`)
    // NEVER auto-approve by binary name. The payload is the real instruction,
    // so the approval key includes it — each distinct inline command is a
    // distinct approval. This blocks the "Allow Always for bash" loophole.
    let inline_payload = extract_inline_code(&binary, argv);
    if inline_payload.is_some() {
        let key = approval_key_for(argv);
        let store = STORE.lock().unwrap();
        if store.always_allowed.contains(&key) {
            return Ok(());
        }
        if store.denied.contains(&key) {
            return Err(format!("Command denied by user: {}", argv.join(" ")));
        }
        return Err(format!("APPROVAL_REQUIRED:{}", key));
    }

    // Non-inline invocation: safe binaries auto-approve.
    if SAFE_BIN_SET.contains(&binary) {
        return Ok(());
    }

    // Unknown binary: check user-recorded decisions.
    let store = STORE.lock().unwrap();
    let key = approval_key_for(argv);
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
    let key = approval_key_for(argv);
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

/// Return the inline-code payload if `argv` invokes a known wrapper in
/// inline-eval mode, else None. Matches the first occurrence of any
/// wrapper-specific flag; the payload is the immediately following arg.
fn extract_inline_code(binary: &str, argv: &[String]) -> Option<String> {
    let flags = INLINE_CODE_WRAPPERS
        .iter()
        .find(|(b, _)| *b == binary)
        .map(|(_, f)| *f)?;
    let mut i = 1;
    while i + 1 < argv.len() {
        if flags.contains(&argv[i].as_str()) {
            return Some(argv[i + 1].clone());
        }
        i += 1;
    }
    None
}

/// Build the approval-store key for `argv`. For inline-code invocations this
/// includes the payload so each distinct command is its own approval; for
/// everything else it's the binary name.
fn approval_key_for(argv: &[String]) -> String {
    if argv.is_empty() {
        return String::new();
    }
    let binary = extract_binary_name(&argv[0]);
    match extract_inline_code(&binary, argv) {
        Some(inline) => format!("{}:inline:{}", binary, inline),
        None => binary,
    }
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

#[cfg(test)]
mod tests {
    use super::*;

    fn argv(parts: &[&str]) -> Vec<String> {
        parts.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn key_for_plain_binary_is_just_the_name() {
        assert_eq!(approval_key_for(&argv(&["git", "status"])), "git");
        assert_eq!(approval_key_for(&argv(&["/usr/bin/git", "log"])), "git");
    }

    #[test]
    fn key_for_inline_shell_includes_payload() {
        let k1 = approval_key_for(&argv(&["bash", "-c", "rm -rf /tmp/foo"]));
        let k2 = approval_key_for(&argv(&["bash", "-c", "echo hello"]));
        assert_eq!(k1, "bash:inline:rm -rf /tmp/foo");
        assert_eq!(k2, "bash:inline:echo hello");
        assert_ne!(k1, k2, "different inline commands must produce different keys");
    }

    #[test]
    fn key_for_node_eval_includes_payload() {
        let k = approval_key_for(&argv(&["node", "-e", "require('fs').unlinkSync('x')"]));
        assert_eq!(k, "node:inline:require('fs').unlinkSync('x')");
    }

    #[test]
    fn key_for_python_dash_c_includes_payload() {
        let k = approval_key_for(&argv(&["python3", "-c", "import os; os.system('ls')"]));
        assert_eq!(k, "python3:inline:import os; os.system('ls')");
    }

    #[test]
    fn inline_wrapper_never_auto_approved_by_binary_name() {
        // Even though `node` is a SAFE_BIN, `node -e <code>` must require
        // explicit approval — otherwise any inline code auto-runs.
        let result = check_allowlist(&argv(&["node", "-e", "console.log(1)"]));
        assert!(
            matches!(result, Err(ref msg) if msg.starts_with("APPROVAL_REQUIRED:node:inline:")),
            "expected APPROVAL_REQUIRED for node -e, got {:?}",
            result
        );
    }

    #[test]
    fn plain_safe_bin_still_auto_approved() {
        assert!(check_allowlist(&argv(&["git", "status"])).is_ok());
        assert!(check_allowlist(&argv(&["ls", "-la"])).is_ok());
    }

    #[test]
    fn allow_always_on_one_inline_does_not_leak_to_another() {
        // Manually seed the store to simulate "Allow Always" on one command.
        {
            let mut store = STORE.lock().unwrap();
            store
                .always_allowed
                .insert("bash:inline:echo approved".to_string());
        }
        // The exact command is allowed...
        assert!(check_allowlist(&argv(&["bash", "-c", "echo approved"])).is_ok());
        // ...but a different inline payload is not.
        let other = check_allowlist(&argv(&["bash", "-c", "echo different"]));
        assert!(
            matches!(other, Err(ref msg) if msg.starts_with("APPROVAL_REQUIRED:")),
            "different payload must re-prompt, got {:?}",
            other
        );
        // Clean up so other tests don't see this entry.
        STORE
            .lock()
            .unwrap()
            .always_allowed
            .remove("bash:inline:echo approved");
    }
}
