/**
 * Hook to fetch and subscribe to Bit City state.
 *
 * Data sources (in priority order):
 * 1. WebSocket push (town_state messages) — real-time, ~2s tick
 * 2. REST polling fallback — every 2s for unauthenticated observers
 *
 * Also provides lerp-interpolated player positions for smooth rendering
 * between the 2-second backend ticks.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  TownGameState,
  TownStateResponse,
  TownDescriptionsResponse,
  TownPlayer,
  TownWsMessage,
  PlayerDescription,
  AgentDescription,
  SpeechBubble,
  WorldMap,
} from '../types/town';

const API_URL =
  (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_BACKEND_URL) ??
  'http://localhost:8000/api/v1';

const WS_URL: string | null =
  (typeof import.meta !== 'undefined' && (import.meta as any).env?.VITE_WS_URL) ?? null;

const POLL_INTERVAL = 2000;

// -- Lerp interpolation for smooth movement ----------------------------------

interface LerpState {
  prev: { x: number; y: number };
  target: { x: number; y: number };
  startTime: number;
  duration: number; // ms — matches tick interval
}

function lerpPosition(lerp: LerpState, now: number): { x: number; y: number } {
  const elapsed = now - lerp.startTime;
  const t = Math.min(1, elapsed / lerp.duration);
  return {
    x: lerp.prev.x + (lerp.target.x - lerp.prev.x) * t,
    y: lerp.prev.y + (lerp.target.y - lerp.prev.y) * t,
  };
}

// -- Hook --------------------------------------------------------------------

export function useTownState(getToken?: () => Promise<string | null>): {
  game: TownGameState | undefined;
  lerpPlayers: () => TownPlayer[];
} {
  const [game, setGame] = useState<TownGameState>();
  const lerpStates = useRef<Map<string, LerpState>>(new Map());
  const latestPlayers = useRef<TownPlayer[]>([]);

  // Update lerp states when new server data arrives
  const updateLerpStates = useCallback((players: TownPlayer[]) => {
    const now = performance.now();
    const newMap = new Map<string, LerpState>();
    for (const p of players) {
      const existing = lerpStates.current.get(p.id);
      if (existing) {
        // Use current interpolated position as prev, new server position as target
        const currentPos = lerpPosition(existing, now);
        newMap.set(p.id, {
          prev: currentPos,
          target: p.position,
          startTime: now,
          duration: POLL_INTERVAL,
        });
      } else {
        // First time seeing this player — snap to position
        newMap.set(p.id, {
          prev: p.position,
          target: p.position,
          startTime: now,
          duration: POLL_INTERVAL,
        });
      }
    }
    lerpStates.current = newMap;
    latestPlayers.current = players;
  }, []);

  // Returns players with lerp-interpolated positions (call per render frame)
  const lerpPlayers = useCallback((): TownPlayer[] => {
    const now = performance.now();
    return latestPlayers.current.map((p) => {
      const lerp = lerpStates.current.get(p.id);
      if (!lerp) return p;
      const pos = lerpPosition(lerp, now);
      return { ...p, position: pos };
    });
  }, []);

  // Process incoming state data (from REST or WS)
  const processState = useCallback(
    (
      stateResp: TownStateResponse,
      descResp: TownDescriptionsResponse,
      speechBubbles?: SpeechBubble[],
    ) => {
      const playerDescs = new Map<string, PlayerDescription>();
      for (const pd of descResp.playerDescriptions) {
        playerDescs.set(pd.playerId, pd);
      }
      const agentDescs = new Map<string, AgentDescription>();
      for (const ad of descResp.agentDescriptions) {
        agentDescs.set(ad.agentId, ad);
      }

      updateLerpStates(stateResp.world.players);

      setGame({
        world: stateResp.world,
        engine: stateResp.engine,
        worldMap: descResp.worldMap,
        playerDescriptions: playerDescs,
        agentDescriptions: agentDescs,
        speechBubbles: speechBubbles ?? stateResp.speechBubbles ?? [],
      });
    },
    [updateLerpStates],
  );

  // -- WebSocket subscription -------------------------------------------------
  useEffect(() => {
    if (!WS_URL || !getToken) return;

    let ws: WebSocket | null = null;
    let cancelled = false;
    let reconnectDelay = 1000;

    const connect = async () => {
      if (cancelled) return;
      let token: string | null = null;
      try {
        token = await getToken();
      } catch {
        /* retry */
      }
      if (cancelled) return;
      if (!token) {
        setTimeout(connect, reconnectDelay);
        return;
      }

      ws = new WebSocket(`${WS_URL}?token=${token}`);

      ws.onopen = () => {
        if (cancelled) {
          ws?.close();
          return;
        }
        reconnectDelay = 1000;
        ws!.send(JSON.stringify({ type: 'town_subscribe' }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as TownWsMessage;
          if (msg.type === 'town_state' && msg.worldState && msg.gameDescriptions) {
            processState(
              {
                world: msg.worldState.world,
                engine: msg.worldState.engine,
                speechBubbles: msg.speechBubbles ?? [],
              },
              msg.gameDescriptions,
              msg.speechBubbles,
            );
          }
        } catch {
          /* malformed message */
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        ws = null;
        setTimeout(connect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 1.5, 10000);
      };

      ws.onerror = () => {
        /* onclose fires after onerror */
      };
    };

    void connect();

    return () => {
      cancelled = true;
      if (ws) {
        ws.onclose = null;
        ws.onerror = null;
        ws.onmessage = null;
        ws.close();
      }
    };
  }, [getToken, processState]);

  // -- REST polling fallback --------------------------------------------------
  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      if (cancelled) return;
      try {
        const [stateRes, descRes] = await Promise.all([
          fetch(`${API_URL}/town/state`),
          fetch(`${API_URL}/town/descriptions`),
        ]);
        if (cancelled) return;
        if (stateRes.ok && descRes.ok) {
          const stateData: TownStateResponse = await stateRes.json();
          const descData: TownDescriptionsResponse = await descRes.json();
          processState(stateData, descData);
        }
      } catch {
        /* retry on next interval */
      }
      if (!cancelled) setTimeout(poll, POLL_INTERVAL);
    };

    void poll();
    return () => {
      cancelled = true;
    };
  }, [processState]);

  return { game, lerpPlayers };
}
