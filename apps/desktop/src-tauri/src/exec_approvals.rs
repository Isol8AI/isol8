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

/// Binaries that can execute arbitrary inline code via a flag.
///
/// When invoked this way, the PAYLOAD is the real instruction — approving
/// `bash` once must NOT grant a blanket allow for every future `bash -c <x>`.
/// The approval key for these includes the inline payload (see
/// `approval_key_for`), so each distinct inline command prompts separately.
///
/// Each entry lists:
///   - `short_letters`: single-char flag letters (e.g. 'c' for `-c`,
///     'e' for `-e`). These match both plain (`-c`) and CLUSTERED
///     (`-lc`, `-Ec`) forms — POSIX shells / Python / Ruby / Perl all
///     accept option clustering. When any listed letter appears in a
///     short-form argv element, the NEXT argv element is the payload.
///   - `long_flags`: long-form flag names without the leading `--`
///     (e.g. "eval" matches `--eval CODE` and `--eval=CODE`). Needed
///     for Node: `node --eval=...` used to slip past the check.
struct InlineWrapper {
    short_letters: &'static [char],
    long_flags: &'static [&'static str],
}

const INLINE_CODE_WRAPPERS: &[(&str, InlineWrapper)] = &[
    ("sh", InlineWrapper { short_letters: &['c'], long_flags: &[] }),
    ("bash", InlineWrapper { short_letters: &['c'], long_flags: &[] }),
    ("zsh", InlineWrapper { short_letters: &['c'], long_flags: &[] }),
    ("fish", InlineWrapper { short_letters: &['c'], long_flags: &[] }),
    ("dash", InlineWrapper { short_letters: &['c'], long_flags: &[] }),
    ("ksh", InlineWrapper { short_letters: &['c'], long_flags: &[] }),
    ("python", InlineWrapper { short_letters: &['c'], long_flags: &[] }),
    ("python3", InlineWrapper { short_letters: &['c'], long_flags: &[] }),
    ("python2", InlineWrapper { short_letters: &['c'], long_flags: &[] }),
    ("node", InlineWrapper { short_letters: &['e', 'p'], long_flags: &["eval", "print"] }),
    ("ruby", InlineWrapper { short_letters: &['e'], long_flags: &[] }),
    ("perl", InlineWrapper { short_letters: &['e', 'E'], long_flags: &[] }),
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
/// inline-eval mode, else None.
///
/// Handles the flag forms each wrapper actually accepts:
///   - plain short:    `bash -c CODE`
///   - clustered:      `bash -lc CODE`, `python -Bc CODE`, `perl -we CODE`
///   - long:           `node --eval CODE`, `node --print CODE`
///   - long with `=`:  `node --eval=CODE`
///
/// The previous implementation only did exact string equality on the flag
/// (`argv[i] == "-c"`), so `-lc`, `-Ec`, `--eval=...` all slipped through
/// the inline-detection path and approval fell back to the bare-binary
/// key — defeating the per-payload approval boundary.
fn extract_inline_code(binary: &str, argv: &[String]) -> Option<String> {
    let cfg = INLINE_CODE_WRAPPERS
        .iter()
        .find(|(b, _)| *b == binary)
        .map(|(_, c)| c)?;

    for i in 1..argv.len() {
        let arg = &argv[i];

        // Long form: --eval, --print, --eval=CODE, --print=CODE
        if let Some(rest) = arg.strip_prefix("--") {
            for &lf in cfg.long_flags {
                if rest == lf {
                    return argv.get(i + 1).cloned();
                }
                // `--eval=CODE` → split on the FIRST `=`
                if rest.len() > lf.len()
                    && rest.starts_with(lf)
                    && rest.as_bytes()[lf.len()] == b'='
                {
                    return Some(rest[lf.len() + 1..].to_string());
                }
            }
            continue;
        }

        // Short form: -c, -lc, -Ec, -cPAYLOAD, -lcPAYLOAD, etc.
        //
        // Per POSIX/getopt, an arg-taking short option can have its value
        // ATTACHED to the flag token. Both `python3 -c CODE` and
        // `python3 -cCODE` are valid, same for `node -eCODE` and
        // `ruby -eCODE`. Under clustering the value attaches to the last
        // letter: `bash -lcCODE` = `-l -c CODE`. Only matching on the
        // "next argv element" misses these attached forms and lets them
        // slip past the inline-approval path — since python/node/ruby are
        // in SAFE_BINS, they'd auto-run arbitrary code with no prompt.
        //
        // So: walk the letters. If we see a short_letter and there's more
        // text after it in this token, that text IS the payload. Otherwise
        // the payload is the next argv element.
        if let Some(letters) = arg.strip_prefix('-').filter(|s| !s.is_empty() && !s.starts_with('-')) {
            let bytes = letters.as_bytes();
            for (idx, c) in letters.char_indices() {
                if cfg.short_letters.contains(&c) {
                    let after = idx + c.len_utf8();
                    if after < bytes.len() {
                        // Attached payload: -cCODE / -lcCODE
                        return Some(letters[after..].to_string());
                    }
                    // Bare flag; payload is the next argv element.
                    return argv.get(i + 1).cloned();
                }
            }
        }
    }
    None
}

/// Build the approval-store key for `argv`.
///
/// For inline-code invocations the key includes the payload so each distinct
/// inline command is its own approval (see `extract_inline_code`).
///
/// For regular invocations the key is the FULL argv[0], not just the
/// basename. Keying on basename ("git") would let any binary called `git`
/// on PATH inherit the approval — an attacker-controlled `/tmp/evil/git`
/// placed earlier in PATH than `/usr/bin/git` would run with the user's
/// prior "Allow Always git" approval. Callers are expected to resolve
/// argv[0] to an absolute path via PATH before calling check_approval
/// (see `resolve_argv0_absolute` in node_invoke.rs); we key on whatever
/// they pass.
fn approval_key_for(argv: &[String]) -> String {
    if argv.is_empty() {
        return String::new();
    }
    // Basename is still used to MATCH the wrapper list (e.g. is argv[0]
    // any known-path "bash"?), but the stored key prefix is the full path.
    let binary_name = extract_binary_name(&argv[0]);
    match extract_inline_code(&binary_name, argv) {
        Some(inline) => format!("{}:inline:{}", argv[0], inline),
        None => argv[0].clone(),
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
    fn key_is_full_argv0_not_basename() {
        // Critical: /usr/bin/git and /tmp/evil/git must NOT share a key,
        // otherwise a PATH-shadowing attacker inherits approvals.
        assert_eq!(approval_key_for(&argv(&["/usr/bin/git", "status"])), "/usr/bin/git");
        assert_eq!(approval_key_for(&argv(&["/tmp/evil/git", "log"])), "/tmp/evil/git");
        assert_ne!(
            approval_key_for(&argv(&["/usr/bin/git", "a"])),
            approval_key_for(&argv(&["/tmp/evil/git", "a"])),
            "different absolute paths to 'git' must produce different approval keys"
        );
    }

    #[test]
    fn key_for_bare_argv0_is_as_given() {
        // When callers haven't resolved argv[0] yet (e.g. tests, preflight
        // checks against the raw agent input), we key on whatever string
        // they passed. Callers resolve via PATH before real approval checks.
        assert_eq!(approval_key_for(&argv(&["git", "status"])), "git");
    }

    #[test]
    fn key_for_inline_shell_includes_payload() {
        let k1 = approval_key_for(&argv(&["/bin/bash", "-c", "rm -rf /tmp/foo"]));
        let k2 = approval_key_for(&argv(&["/bin/bash", "-c", "echo hello"]));
        assert_eq!(k1, "/bin/bash:inline:rm -rf /tmp/foo");
        assert_eq!(k2, "/bin/bash:inline:echo hello");
        assert_ne!(k1, k2, "different inline commands must produce different keys");
    }

    #[test]
    fn key_for_node_eval_includes_payload() {
        let k = approval_key_for(&argv(&["/usr/local/bin/node", "-e", "require('fs').unlinkSync('x')"]));
        assert_eq!(k, "/usr/local/bin/node:inline:require('fs').unlinkSync('x')");
    }

    #[test]
    fn key_for_python_dash_c_includes_payload() {
        let k = approval_key_for(&argv(&["/usr/bin/python3", "-c", "import os; os.system('ls')"]));
        assert_eq!(k, "/usr/bin/python3:inline:import os; os.system('ls')");
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
        let seeded_key = "/bin/bash:inline:echo approved".to_string();
        {
            let mut store = STORE.lock().unwrap();
            store.always_allowed.insert(seeded_key.clone());
        }
        // The exact command is allowed...
        assert!(check_allowlist(&argv(&["/bin/bash", "-c", "echo approved"])).is_ok());
        // ...but a different inline payload is not.
        let other = check_allowlist(&argv(&["/bin/bash", "-c", "echo different"]));
        assert!(
            matches!(other, Err(ref msg) if msg.starts_with("APPROVAL_REQUIRED:")),
            "different payload must re-prompt, got {:?}",
            other
        );
        // Clean up.
        STORE.lock().unwrap().always_allowed.remove(&seeded_key);
    }

    #[test]
    fn clustered_short_flag_still_detected_as_inline() {
        // bash supports option clustering: `-lc` is `-l` + `-c`. Earlier we
        // only matched exact "-c", so `bash -lc CODE` slipped past the inline
        // gate and got the plain-bash approval key — a single "Allow Always
        // bash" then auto-ran every future inline command.
        let k1 = approval_key_for(&argv(&["/bin/bash", "-lc", "rm -rf /tmp/foo"]));
        assert_eq!(k1, "/bin/bash:inline:rm -rf /tmp/foo");

        let k2 = approval_key_for(&argv(&["/usr/bin/python3", "-Bc", "import os"]));
        assert_eq!(k2, "/usr/bin/python3:inline:import os");

        let k3 = approval_key_for(&argv(&["/usr/bin/perl", "-we", "print 1"]));
        assert_eq!(k3, "/usr/bin/perl:inline:print 1");
    }

    #[test]
    fn node_long_flags_with_and_without_equals_detected_as_inline() {
        // node --eval CODE  and  node --eval=CODE  must both key as inline.
        let k_spaced = approval_key_for(&argv(&["/usr/local/bin/node", "--eval", "console.log(1)"]));
        assert_eq!(k_spaced, "/usr/local/bin/node:inline:console.log(1)");

        let k_equals = approval_key_for(&argv(&["/usr/local/bin/node", "--eval=console.log(2)"]));
        assert_eq!(k_equals, "/usr/local/bin/node:inline:console.log(2)");

        let k_print = approval_key_for(&argv(&["/usr/local/bin/node", "--print=2+2"]));
        assert_eq!(k_print, "/usr/local/bin/node:inline:2+2");
    }

    #[test]
    fn clustered_inline_requires_approval_and_does_not_leak_across_payloads() {
        // The end-to-end invariant: one Allow-Always on `bash -lc A` must
        // NOT approve `bash -lc B`.
        let seeded = "/bin/bash:inline:echo approved-bash-lc".to_string();
        STORE.lock().unwrap().always_allowed.insert(seeded.clone());
        assert!(check_allowlist(&argv(&["/bin/bash", "-lc", "echo approved-bash-lc"])).is_ok());
        let other = check_allowlist(&argv(&["/bin/bash", "-lc", "echo different"]));
        assert!(
            matches!(other, Err(ref msg) if msg.starts_with("APPROVAL_REQUIRED:/bin/bash:inline:")),
            "-lc with different payload must re-prompt, got {:?}",
            other
        );
        STORE.lock().unwrap().always_allowed.remove(&seeded);
    }

    #[test]
    fn attached_short_flag_payload_detected_as_inline() {
        // getopt-style: short option with required argument can have the
        // value attached to the flag token. `python3 -cCODE`, `node -eCODE`
        // etc. are valid at runtime. If we don't recognize these as inline,
        // SAFE_BIN auto-approval runs arbitrary code with no prompt.
        let k_py = approval_key_for(&argv(&["/usr/bin/python3", "-cprint(1)"]));
        assert_eq!(k_py, "/usr/bin/python3:inline:print(1)");

        let k_node = approval_key_for(&argv(&["/usr/local/bin/node", "-econsole.log(2)"]));
        assert_eq!(k_node, "/usr/local/bin/node:inline:console.log(2)");

        let k_ruby = approval_key_for(&argv(&["/usr/bin/ruby", "-eputs(1)"]));
        assert_eq!(k_ruby, "/usr/bin/ruby:inline:puts(1)");

        let k_perl = approval_key_for(&argv(&["/usr/bin/perl", "-Eprint 1"]));
        assert_eq!(k_perl, "/usr/bin/perl:inline:print 1");
    }

    #[test]
    fn attached_payload_after_clustered_flags_detected() {
        // Clustering + attached payload: `bash -lcCODE` = `-l -c CODE`.
        let k = approval_key_for(&argv(&["/bin/bash", "-lcrm -rf /"]));
        assert_eq!(k, "/bin/bash:inline:rm -rf /");

        // python `-Bcimport os`: -B then -c with payload "import os"
        let k2 = approval_key_for(&argv(&["/usr/bin/python3", "-Bcimport os"]));
        assert_eq!(k2, "/usr/bin/python3:inline:import os");
    }

    #[test]
    fn attached_payload_requires_approval() {
        // End-to-end: the SAFE_BINS auto-approve path is NOT reached for
        // attached inline invocations.
        let result = check_allowlist(&argv(&["/usr/bin/python3", "-cos.system('x')"]));
        assert!(
            matches!(result, Err(ref msg) if msg.starts_with("APPROVAL_REQUIRED:/usr/bin/python3:inline:")),
            "attached python -c payload must require approval, got {:?}",
            result
        );
    }

    #[test]
    fn path_shadowing_does_not_inherit_approval() {
        // The defense: even if the user previously "Allow Always"ed a real
        // binary like /usr/bin/foo, an attacker dropping /tmp/evil/foo on
        // PATH does NOT get auto-approved — different absolute path,
        // different key, still prompts.
        let approved_path = "/usr/bin/some-uncommon-bin".to_string();
        {
            let mut store = STORE.lock().unwrap();
            store.always_allowed.insert(approved_path.clone());
        }
        // Real binary path is approved.
        assert!(check_allowlist(&argv(&[&approved_path, "--help"])).is_ok());
        // Shadowing binary is NOT approved.
        let shadow = check_allowlist(&argv(&["/tmp/evil/some-uncommon-bin", "--help"]));
        assert!(
            matches!(shadow, Err(ref msg) if msg.starts_with("APPROVAL_REQUIRED:")),
            "shadow path must re-prompt, got {:?}",
            shadow
        );
        // Clean up.
        STORE.lock().unwrap().always_allowed.remove(&approved_path);
    }
}
