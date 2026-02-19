/**
 * Isol8 REST client — replaces the convex/react npm package entirely.
 *
 * All network calls go to the Isol8 backend (VITE_BACKEND_URL). There is
 * no connection to Convex — the class/hook names are kept only so that
 * existing component imports work without changes.
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

// ---------------------------------------------------------------------------
// Client — talks to the Isol8 REST backend
// ---------------------------------------------------------------------------

/**
 * Exported as `ConvexReactClient` so existing imports keep working.
 * Internally this is just an HTTP client pointed at the Isol8 backend.
 *
 * The constructor signature matches the old Convex one (url string + opts)
 * so ConvexClientProvider.tsx doesn't need changes. Both arguments are
 * ignored — the real URL comes from VITE_BACKEND_URL.
 */
export class ConvexReactClient {
  private _apiUrl: string;
  private _getToken: (() => Promise<string | null>) | null = null;

  constructor(_ignoredUrl?: string, _ignoredOpts?: Record<string, any>) {
    this._apiUrl =
      (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_BACKEND_URL) ??
      'http://localhost:8000/api/v1';
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
    } catch {
      // Token fetch failed — continue without auth.
    }
    return {};
  }

  /** Set the token-getter callback. Called by ConvexProviderWithClerk. */
  setAuth(getToken: () => Promise<string | null>) {
    this._getToken = getToken;
  }

  /** Clear auth state. */
  clearAuth() {
    this._getToken = null;
  }

  // -- public API ----------------------------------------------------------

  /** POST to the Isol8 backend. */
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

  /** GET from the Isol8 backend. Args become query-string params. */
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

  /**
   * Poll a query for changes. Returns an object with localQueryResult()
   * and onUpdate(callback) — the interface used by sendInput.ts.
   */
  watchQuery(ref: FunctionRef, args?: Record<string, any>) {
    let latestResult: any = undefined;
    let listeners: Array<() => void> = [];
    let disposed = false;

    const poll = async () => {
      if (disposed) return;
      try {
        latestResult = await this.query(ref, args);
      } catch {
        // Retry silently on next tick.
      }
      for (const cb of listeners) {
        try { cb(); } catch { /* swallow */ }
      }
      if (!disposed) {
        setTimeout(poll, 500);
      }
    };

    void poll();

    return {
      localQueryResult: () => latestResult,
      onUpdate: (cb: () => void): (() => void) => {
        listeners.push(cb);
        return () => {
          disposed = true;
          listeners = [];
        };
      },
    };
  }
}

// ---------------------------------------------------------------------------
// React contexts
// ---------------------------------------------------------------------------

const ClientContext = createContext<ConvexReactClient | null>(null);

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
}
const AuthStateContext = createContext<AuthState>({ isAuthenticated: false, isLoading: true });

/** Wraps children with the Isol8 client context (no auth). */
export function ConvexProvider({
  client,
  children,
}: {
  client: ConvexReactClient;
  children: ReactNode;
}) {
  return createElement(ClientContext.Provider, { value: client }, children);
}

/**
 * Wraps children with the Isol8 client context AND Clerk auth.
 *
 * Accepts `useAuth` (the Clerk useAuth hook) and wires it into the client
 * so that all fetch calls include the Authorization header.
 */
export function ConvexProviderWithClerk({
  client,
  useAuth: useAuthHook,
  children,
}: {
  client: ConvexReactClient;
  useAuth: () => {
    getToken: (opts?: any) => Promise<string | null>;
    isSignedIn: boolean | undefined;
    isLoaded: boolean | undefined;
  };
  children: ReactNode;
}) {
  const auth = useAuthHook();

  useEffect(() => {
    client.setAuth(() => auth.getToken());
    return () => client.clearAuth();
  }, [client, auth.getToken]);

  const authState: AuthState = {
    isAuthenticated: !!auth.isSignedIn,
    isLoading: !auth.isLoaded,
  };

  return createElement(
    AuthStateContext.Provider,
    { value: authState },
    createElement(ClientContext.Provider, { value: client }, children),
  );
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** Get the client from context. */
export function useConvex(): ConvexReactClient {
  const client = useContext(ClientContext);
  if (!client) {
    throw new Error('useConvex must be used within a <ConvexProvider>');
  }
  return client;
}

/** Get auth state. Mirrors the original convex/react useConvexAuth(). */
export function useConvexAuth(): AuthState {
  return useContext(AuthStateContext);
}

/**
 * Poll an Isol8 REST endpoint. Returns undefined while loading or skipped.
 *
 *   useQuery(api.world.worldState, { worldId })
 *   useQuery(api.world.worldState, worldId ? { worldId } : 'skip')
 */
export function useQuery(ref: FunctionRef, args?: Record<string, any> | 'skip'): any {
  const client = useContext(ClientContext);
  const [data, setData] = useState<any>(undefined);
  const argsKey = args === 'skip' ? 'skip' : JSON.stringify(args ?? {});

  useEffect(() => {
    if (!client || args === 'skip') {
      setData(undefined);
      return;
    }

    let cancelled = false;
    const resolved = (typeof args === 'object' && args !== null ? args : undefined) as
      | Record<string, any>
      | undefined;

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

/**
 * Returns a stable callback that POSTs to the Isol8 backend.
 *
 *   const heartbeat = useMutation(api.world.heartbeatWorld);
 *   await heartbeat({ worldId });
 */
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
