import open from "open";

export async function deviceCodeAuth(opts: { backendBaseUrl: string }): Promise<string> {
  const startResp = await fetch(`${opts.backendBaseUrl}/api/v1/marketplace/cli/auth/start`, {
    method: "POST",
  });
  const start = (await startResp.json()) as { device_code: string; browser_url: string };
  console.log(`Open in your browser: ${start.browser_url}`);
  await open(start.browser_url);

  const deadline = Date.now() + 5 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 2000));
    const pollResp = await fetch(
      `${opts.backendBaseUrl}/api/v1/marketplace/cli/auth/poll?device_code=${start.device_code}`
    );
    if (pollResp.status === 200) {
      const body = (await pollResp.json()) as { status: string; jwt?: string };
      if (body.status === "authorized") return body.jwt!;
    }
  }
  throw new Error("auth timed out — please try again");
}
