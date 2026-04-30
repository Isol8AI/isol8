import { spawn } from "bun";

export interface SandboxResult {
  exitCode: number | null;
  stdout: string;
  stderr: string;
  timedOut: boolean;
  durationMs: number;
}

export interface SandboxOpts {
  cwd: string;
  command: string[];
  input: string;
  timeoutMs: number;
  memoryMb: number;
}

export async function runSandboxed(opts: SandboxOpts): Promise<SandboxResult> {
  const start = Date.now();
  // Bun.spawn API. Network and filesystem caps are enforced by:
  //   - Process boundary: Fargate task has no host-network share.
  //   - Memory: ulimit/cgroups via the Fargate task definition.
  //   - CPU/timeout: enforced here via setTimeout + .kill().
  // For v1 we trust the Fargate process boundary and do not use seccomp/gVisor.
  // Hardening to a more restrictive sandbox lands in Phase 2.
  const child = spawn({
    cmd: opts.command,
    cwd: opts.cwd,
    stdin: "pipe",
    stdout: "pipe",
    stderr: "pipe",
    env: { PATH: "/usr/bin:/bin" },
  });

  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    // SIGKILL ensures the process exits even if it's ignoring SIGTERM.
    child.kill("SIGKILL");
  }, opts.timeoutMs);

  if (opts.input) child.stdin.write(opts.input);
  child.stdin.end();

  // Drain stdout/stderr concurrently with the process. We don't wait on the
  // streams to close after a timeout because grandchild processes (e.g. a
  // shell's `sleep`) can keep the pipe fds open even after the direct child
  // is killed. Instead we await `child.exited`, then collect whatever was
  // buffered with a short grace period.
  const stdoutPromise = new Response(child.stdout).text().catch(() => "");
  const stderrPromise = new Response(child.stderr).text().catch(() => "");

  const exitCode = await child.exited;
  clearTimeout(timer);

  // Give the streams a brief window to flush. If grandchildren are holding
  // the fds open, fall back to empty strings rather than hanging.
  const drainTimeout = new Promise<["", ""]>((resolve) =>
    setTimeout(() => resolve(["", ""]), 100),
  );
  const [stdout, stderr] = await Promise.race([
    Promise.all([stdoutPromise, stderrPromise]),
    drainTimeout,
  ]);

  return {
    exitCode,
    stdout,
    stderr,
    timedOut,
    durationMs: Date.now() - start,
  };
}
