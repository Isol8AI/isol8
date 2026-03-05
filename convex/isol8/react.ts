/**
 * Isol8 Convex-compatible client — replaces the convex/react npm package.
 *
 * Game state queries (/town/state, /town/descriptions) are delivered via the
 * shared API Gateway WebSocket (same one used for chat).  The client sends
 * {"type":"town_subscribe"} on connect and receives {"type":"town_state",…}
 * messages whenever state changes.  Both queries update from the same message,
 * giving us the same atomic update guarantee that Convex subscriptions provide.
 *
 * Non-game queries (user-status, input-status) fall back to REST polling.
 *
 * When VITE_WS_URL is not set (local dev), the WebSocket path is skipped and
 * all queries use REST polling.
 */

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';
import type { ReactNode } from 'react';

// ---------------------------------------------------------------------------
// FunctionRef — shape of the objects in our api.js endpoint mapping
// ---------------------------------------------------------------------------

interface FunctionRef {
  _type: 'query' | 'mutation';
  endpoint: string;
}

// Map from WebSocket message keys to the endpoint they serve
const WS_KEY_FOR_ENDPOINT: Record<string, string> = {
  '/town/state': 'worldState',
  '/town/descriptions': 'gameDescriptions',
};

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export class ConvexReactClient {
  private _apiUrl: string;
  private _wsUrl: string | null;
  private _getToken: (() => Promise<string | null>) | null = null;

  // WebSocket state
  private _ws: WebSocket | null = null;
  private _wsCache: Record<string, any> = {};
  private _wsListeners: Set<() => void> = new Set();
  private _reconnectDelay = 1000;
  private _connectAttempt = 0; // Guards against duplicate connections

  constructor(_ignoredUrl?: string, _ignoredOpts?: Record<string, any>) {
    this._apiUrl =
      (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_BACKEND_URL) ??
      'http://localhost:8000/api/v1';
    this._wsUrl =
      (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_WS_URL) ?? null;
    // Don't connect WS here — wait for setAuth() so we have a token
  }

  // -- helpers -------------------------------------------------------------

  private _url(endpoint: string): string {
    return `${this._apiUrl}${endpoint}`;
  }

  private async _authHeaders(): Promise<Record<string, string>> {
    if (!this._getToken) return {};
    try {
      const token = await this._getToken();
      if (token) return { Authorization: `Bearer ${token}` };
    } catch { /* continue without auth */ }
    return {};
  }

  setAuth(getToken: () => Promise<string | null>) {
    this._getToken = getToken;
    // (Re)connect the WebSocket now that we have auth
    if (this._wsUrl) {
      this._closeWs();
      void this._connectWs();
    }
  }

  clearAuth() {
    this._getToken = null;
    this._closeWs();
  }

  // -- WebSocket (API Gateway) ---------------------------------------------

  private _closeWs() {
    if (this._ws) {
      // Detach handlers to prevent the onclose reconnect loop
      const ws = this._ws;
      ws.onclose = null;
      ws.onerror = null;
      ws.onmessage = null;
      ws.close();
      this._ws = null;
    }
    // Invalidate any pending reconnect
    this._connectAttempt++;
  }

  private async _connectWs() {
    if (!this._wsUrl || !this._getToken) return;

    const attempt = ++this._connectAttempt;

    // Get a fresh Clerk token for the API Gateway Lambda authorizer
    let token: string | null = null;
    try {
      token = await this._getToken();
    } catch { /* no token yet */ }

    // Bail if superseded by a newer attempt (setAuth called again, clearAuth, etc.)
    if (attempt !== this._connectAttempt) return;

    if (!token) {
      // Auth not ready yet — retry shortly
      setTimeout(() => {
        if (attempt === this._connectAttempt) void this._connectWs();
      }, this._reconnectDelay);
      return;
    }

    const wsUrl = `${this._wsUrl}?token=${token}`;
    try {
      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        if (attempt !== this._connectAttempt) { ws.close(); return; }
        this._ws = ws;
        this._reconnectDelay = 1000;
        // Subscribe to town state updates on the shared WebSocket
        ws.send(JSON.stringify({ type: 'town_subscribe' }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.type === 'town_state') {
            // Server sends: { type:"town_state", worldState:{…}, gameDescriptions:{…} }
            // Update cache then notify all listeners (React batches setState)
            if (msg.worldState) this._wsCache['/town/state'] = msg.worldState;
            if (msg.gameDescriptions) this._wsCache['/town/descriptions'] = msg.gameDescriptions;
            for (const cb of this._wsListeners) {
              try { cb(); } catch { /* swallow */ }
            }
          }
          // Ignore other message types (chat, pong, etc.)
        } catch { /* malformed message */ }
      };

      ws.onclose = () => {
        if (attempt !== this._connectAttempt) return;
        this._ws = null;
        // Reconnect with backoff (gets a fresh token each time)
        setTimeout(() => {
          if (attempt === this._connectAttempt) void this._connectWs();
        }, this._reconnectDelay);
        this._reconnectDelay = Math.min(this._reconnectDelay * 1.5, 10000);
      };

      ws.onerror = () => { /* onclose fires after onerror */ };
    } catch {
      setTimeout(() => {
        if (attempt === this._connectAttempt) void this._connectWs();
      }, this._reconnectDelay);
      this._reconnectDelay = Math.min(this._reconnectDelay * 1.5, 10000);
    }
  }

  /** Read the latest cached value for a WebSocket-delivered endpoint. */
  getWsCached(endpoint: string): any {
    return this._wsCache[endpoint];
  }

  /** Listen for any WebSocket data change. Returns unsubscribe function. */
  onWsUpdate(cb: () => void): () => void {
    this._wsListeners.add(cb);
    return () => { this._wsListeners.delete(cb); };
  }

  /** Whether the API Gateway WebSocket path is available (VITE_WS_URL set). */
  get wsEnabled(): boolean {
    return this._wsUrl !== null;
  }

  // -- REST ----------------------------------------------------------------

  async mutation(ref: FunctionRef, args?: Record<string, any>): Promise<any> {
    const authHeaders = await this._authHeaders();
    const res = await fetch(this._url(ref.endpoint), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders },
      body: JSON.stringify(args ?? {}),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Mutation ${ref.endpoint} failed (${res.status}): ${text}`);
    }
    return res.json();
  }

  async query(ref: FunctionRef, args?: Record<string, any>): Promise<any> {
    let url = this._url(ref.endpoint);
    if (args && Object.keys(args).length > 0) {
      const params = new URLSearchParams();
      for (const [k, v] of Object.entries(args)) {
        params.set(k, typeof v === 'string' ? v : JSON.stringify(v));
      }
      url += `?${params.toString()}`;
    }
    const authHeaders = await this._authHeaders();
    const res = await fetch(url, { method: 'GET', headers: authHeaders });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`Query ${ref.endpoint} failed (${res.status}): ${text}`);
    }
    return res.json();
  }

  watchQuery(ref: FunctionRef, args?: Record<string, any>) {
    let latestResult: any = undefined;
    let listeners: Array<() => void> = [];
    let disposed = false;

    const poll = async () => {
      if (disposed) return;
      try { latestResult = await this.query(ref, args); } catch { /* retry */ }
      for (const cb of listeners) { try { cb(); } catch { /* swallow */ } }
      if (!disposed) setTimeout(poll, 500);
    };
    void poll();

    return {
      localQueryResult: () => latestResult,
      onUpdate: (cb: () => void): (() => void) => {
        listeners.push(cb);
        return () => { disposed = true; listeners = []; };
      },
    };
  }
}

// ---------------------------------------------------------------------------
// React contexts
// ---------------------------------------------------------------------------

const ClientContext = createContext<ConvexReactClient | null>(null);

interface AuthState { isAuthenticated: boolean; isLoading: boolean; }
const AuthStateContext = createContext<AuthState>({ isAuthenticated: false, isLoading: true });

export function ConvexProvider({ client, children }: { client: ConvexReactClient; children: ReactNode }) {
  return createElement(ClientContext.Provider, { value: client }, children);
}

export function ConvexProviderWithClerk({
  client, useAuth: useAuthHook, children,
}: {
  client: ConvexReactClient;
  useAuth: () => { getToken: (opts?: any) => Promise<string | null>; isSignedIn: boolean | undefined; isLoaded: boolean | undefined };
  children: ReactNode;
}) {
  const auth = useAuthHook();
  useEffect(() => { client.setAuth(() => auth.getToken()); return () => client.clearAuth(); }, [client, auth.getToken]);
  const authState: AuthState = { isAuthenticated: !!auth.isSignedIn, isLoading: !auth.isLoaded };
  return createElement(AuthStateContext.Provider, { value: authState }, createElement(ClientContext.Provider, { value: client }, children));
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useConvex(): ConvexReactClient {
  const client = useContext(ClientContext);
  if (!client) throw new Error('useConvex must be used within a <ConvexProvider>');
  return client;
}

export function useConvexAuth(): AuthState {
  return useContext(AuthStateContext);
}

/**
 * Subscribe to a query. Game-state endpoints use the API Gateway WebSocket
 * (atomic updates); everything else falls back to REST polling.
 *
 * When VITE_WS_URL is not set (local dev), ALL queries use REST polling.
 */
export function useQuery(ref: FunctionRef, args?: Record<string, any> | 'skip'): any {
  const client = useContext(ClientContext);
  const [data, setData] = useState<any>(undefined);
  const argsKey = args === 'skip' ? 'skip' : JSON.stringify(args ?? {});

  useEffect(() => {
    if (!client || args === 'skip') { setData(undefined); return; }

    const resolved = (typeof args === 'object' && args !== null ? args : undefined) as
      | Record<string, any> | undefined;

    // WebSocket path — /town/state and /town/descriptions are pushed by server.
    // Also starts REST polling as fallback for unauthenticated observers
    // (WS requires auth, so it won't connect for spectators).
    if (client.wsEnabled && ref.endpoint in WS_KEY_FOR_ENDPOINT) {
      const cached = client.getWsCached(ref.endpoint);
      if (cached !== undefined) setData(cached);

      // REST polling fallback — runs until WS starts delivering data
      let cancelled = false;
      const fetchRest = async () => {
        if (cancelled) return;
        if (client.getWsCached(ref.endpoint) !== undefined) return;
        try {
          const result = await client.query(ref, resolved);
          if (!cancelled && client.getWsCached(ref.endpoint) === undefined) setData(result);
        } catch { /* retry on next interval */ }
      };
      void fetchRest();
      const pollId = setInterval(fetchRest, 2000);

      const unsub = client.onWsUpdate(() => {
        const val = client.getWsCached(ref.endpoint);
        if (val !== undefined) {
          setData(val);
          clearInterval(pollId);
        }
      });
      return () => { cancelled = true; clearInterval(pollId); unsub(); };
    }

    // REST polling fallback
    let cancelled = false;
    const fetchData = async () => {
      try {
        const result = await client.query(ref, resolved);
        if (!cancelled) setData(result);
      } catch (err) {
        console.warn(`useQuery(${ref.endpoint}) error:`, err);
      }
    };
    void fetchData();
    const id = setInterval(fetchData, 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, [client, ref?.endpoint, argsKey]);

  return data;
}

export function useMutation(ref: FunctionRef): (args?: Record<string, any>) => Promise<any> {
  const client = useContext(ClientContext);
  const clientRef = useRef(client);
  clientRef.current = client;
  return useCallback(
    async (args?: Record<string, any>) => {
      if (!clientRef.current) throw new Error('useMutation: no ConvexProvider');
      return clientRef.current.mutation(ref, args);
    },
    [ref?.endpoint],
  );
}
