"use client";

/**
 * Node Bridge — connects the Tauri desktop app's local tool execution
 * to the OpenClaw gateway via a browser WebSocket.
 *
 * The macOS .app bundle's in-process TLS interferes with direct Rust
 * WebSocket connections, so the browser WS (which works in WKWebView)
 * handles the gateway protocol while Tauri IPC handles local execution.
 *
 * Flow:
 *   Browser WS ←→ API Gateway ←→ Backend ←→ OpenClaw container
 *                                    ↕
 *   Tauri IPC  ←→ Rust backend (exec commands on user's Mac)
 */

import { useEffect, useRef, useCallback } from "react";
import { useAuth } from "@clerk/nextjs";

const RECONNECT_DELAYS = [1000, 2000, 4000, 8000, 16000];
const MAX_RECONNECT = 5;

function getWebSocketUrl(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL;
  }
  const apiUrl =
    process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
  return apiUrl
    .replace(/^https:\/\//, "wss://")
    .replace(/^http:\/\//, "ws://")
    .replace("api-", "ws-")
    .replace(/\/api\/v1$/, "");
}

interface NodeInvokeRequest {
  id: string;
  nodeId: string;
  command: string;
  paramsJSON?: string;
  timeoutMs?: number;
}

interface NodeInvokeResult {
  id: string;
  nodeId: string;
  ok: boolean;
  payloadJSON?: string;
  error?: { code: string; message: string };
}

/**
 * Hook that runs only inside the Tauri desktop app.
 * Creates a second WebSocket to the gateway as role:"node",
 * and bridges invoke requests to Rust via Tauri IPC.
 */
export function useNodeBridge(onStatusChange?: (status: string) => void) {
  const { getToken } = useAuth();
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const statusRef = useRef<(s: string) => void>(onStatusChange || (() => {}));

  const cleanup = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close(1000, "cleanup");
      wsRef.current = null;
    }
  }, []);

  useEffect(() => {
    // Only run inside Tauri desktop app
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const tauri = (window as any).__TAURI__;
    if (!tauri?.core?.invoke) return;

    let stopped = false;

    async function connect() {
      if (stopped) return;

      try {
        const token = await getToken();
        if (!token) {
          // Not authenticated yet, retry later
          reconnectTimerRef.current = setTimeout(connect, 3000);
          return;
        }

        const wsUrl = getWebSocketUrl();
        const ws = new WebSocket(`${wsUrl}?token=${token}`);
        wsRef.current = ws;

        ws.onopen = () => {
          console.log("[node-bridge] WebSocket connected, waiting for challenge");
          reconnectRef.current = 0;
        };

        ws.onmessage = async (event) => {
          if (!event.data || typeof event.data !== "string") return;
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          let data: any;
          try {
            data = JSON.parse(event.data);
          } catch {
            return;
          }

          const msgType = data.type as string;

          // Handle connect.challenge → send connect with role:"node"
          if (msgType === "event" && data.event === "connect.challenge") {
            console.log("[node-bridge] Got challenge, sending node connect");
            const connectMsg = {
              type: "req",
              id: crypto.randomUUID(),
              method: "connect",
              params: {
                minProtocol: 3,
                maxProtocol: 3,
                client: {
                  id: "isol8-desktop",
                  displayName: "Isol8 Desktop",
                  version: "1.0.0",
                  platform: "macos",
                  mode: "node",
                  instanceId: crypto.randomUUID(),
                },
                role: "node",
                scopes: [],
                caps: ["system"],
                commands: [
                  "system.run.prepare",
                  "system.run",
                  "system.which",
                  "system.execApprovals.get",
                  "system.execApprovals.set",
                ],
                pathEnv: "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                auth: {},
              },
            };
            ws.send(JSON.stringify(connectMsg));
            return;
          }

          // Handle hello-ok (connect response)
          if (msgType === "res" && data.ok && data.payload?.protocol) {
            console.log("[node-bridge] Connected as node (hello-ok)");
            statusRef.current("connected");
            // Also notify Rust side
            tauri.core.invoke("set_node_connected", { connected: true }).catch(() => {});
            return;
          }

          // Handle node.invoke.request → forward to Rust
          if (msgType === "event" && data.event === "node.invoke.request" && data.payload) {
            const req = data.payload as NodeInvokeRequest;
            console.log(`[node-bridge] Invoke: ${req.command} (${req.id})`);

            try {
              // Execute via Tauri IPC
              const resultJson = await tauri.core.invoke("execute_node_command", {
                id: req.id,
                nodeId: req.nodeId,
                command: req.command,
                paramsJson: req.paramsJSON || "{}",
                timeoutMs: req.timeoutMs || 30000,
              }) as string;

              const result: NodeInvokeResult = JSON.parse(resultJson);

              // Send result back to gateway
              ws.send(JSON.stringify({
                type: "req",
                id: crypto.randomUUID(),
                method: "node.invoke.result",
                params: result,
              }));
            } catch (err) {
              // Send error result
              ws.send(JSON.stringify({
                type: "req",
                id: crypto.randomUUID(),
                method: "node.invoke.result",
                params: {
                  id: req.id,
                  nodeId: req.nodeId,
                  ok: false,
                  error: {
                    code: "EXEC_ERROR",
                    message: String(err),
                  },
                } satisfies NodeInvokeResult,
              }));
            }
            return;
          }

          // Ignore other messages (pong, tick, etc.)
        };

        ws.onclose = (event) => {
          wsRef.current = null;
          statusRef.current("disconnected");
          tauri.core.invoke("set_node_connected", { connected: false }).catch(() => {});

          if (stopped || event.code === 1000) return;

          if (reconnectRef.current < MAX_RECONNECT) {
            const delay = RECONNECT_DELAYS[reconnectRef.current] || 16000;
            reconnectRef.current++;
            console.log(`[node-bridge] Reconnecting in ${delay}ms...`);
            reconnectTimerRef.current = setTimeout(connect, delay);
          }
        };

        ws.onerror = () => {};
      } catch (err) {
        console.error("[node-bridge] Connect error:", err);
        if (!stopped && reconnectRef.current < MAX_RECONNECT) {
          reconnectTimerRef.current = setTimeout(connect, 3000);
        }
      }
    }

    connect();

    return () => {
      stopped = true;
      cleanup();
    };
  }, [getToken, cleanup]);
}
