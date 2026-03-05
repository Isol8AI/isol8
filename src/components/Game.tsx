import { useRef, useState } from 'react';
import PixiGame from './PixiGame.tsx';

import { useElementSize } from 'usehooks-ts';
import { Stage } from '@pixi/react';
import { ConvexProvider, useConvex, useConvexAuth, useMutation, useQuery } from 'convex/react';
import PlayerDetails from './PlayerDetails.tsx';
import { api } from '../../convex/_generated/api';
import { useWorldHeartbeat } from '../hooks/useWorldHeartbeat.ts';
import { useHistoricalTime } from '../hooks/useHistoricalTime.ts';
import { DebugTimeManager } from './DebugTimeManager.tsx';
import { GameId } from '../../convex/aiTown/ids.ts';
import { useServerGame } from '../hooks/serverGame.ts';

export const SHOW_DEBUG_UI = !!import.meta.env.VITE_SHOW_DEBUG_UI;

export default function Game() {
  const convex = useConvex();
  const [selectedElement, setSelectedElement] = useState<{
    kind: 'player';
    id: GameId<'players'>;
  }>();
  const [gameWrapperRef, { width, height }] = useElementSize();

  const worldStatus = useQuery(api.world.defaultWorldStatus);
  const worldId = worldStatus?.worldId;
  const engineId = worldStatus?.engineId;

  const game = useServerGame(worldId);

  // Send a periodic heartbeat to our world to keep it alive.
  useWorldHeartbeat();

  const { isAuthenticated } = useConvexAuth();
  const joinWorld = useMutation(api.world.joinWorld);

  const humanTokenIdentifier = useQuery(api.world.userStatus, worldId ? { worldId } : 'skip') ?? null;
  const humanPlayerId = game ? [...game.world.players.values()].find(
    (p) => p.human === humanTokenIdentifier,
  )?.id : undefined;

  const handleJoin = async () => {
    if (!worldId) return;
    try {
      await joinWorld({ worldId });
    } catch (e) {
      console.error('Failed to join:', e);
    }
  };

  const worldState = useQuery(api.world.worldState, worldId ? { worldId } : 'skip');
  const { historicalTime, timeManager } = useHistoricalTime(worldState?.engine);

  const scrollViewRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<any>(null);

  if (!worldId || !engineId || !game) {
    return (
      <div className="flex items-center justify-center w-full h-full text-brown-300 font-body text-lg">
        Loading town...
      </div>
    );
  }
  return (
    <>
      {SHOW_DEBUG_UI && <DebugTimeManager timeManager={timeManager} width={200} height={100} />}
      <div className="flex w-full h-full">
        {/* Map area — fills remaining space */}
        <div className="relative flex-1 overflow-hidden bg-brown-900" ref={gameWrapperRef}>
          <div className="absolute inset-0">
            <Stage width={width} height={height} options={{ backgroundColor: 0x7ab5ff }}>
              <ConvexProvider client={convex}>
                <PixiGame
                  game={game}
                  worldId={worldId}
                  engineId={engineId}
                  width={width}
                  height={height}
                  historicalTime={historicalTime}
                  setSelectedElement={setSelectedElement}
                  viewportRef={viewportRef}
                />
              </ConvexProvider>
            </Stage>
          </div>
          {/* Zoom controls */}
          <div className="absolute bottom-4 right-4 z-10 flex flex-col gap-1">
            <button
              className="w-8 h-8 bg-clay-700/80 hover:bg-clay-600 text-brown-100 rounded text-lg font-bold"
              onClick={() => {
                const vp = viewportRef.current;
                if (vp) vp.animate({ scale: Math.min(3.0, vp.scale.x * 1.3), time: 200 });
              }}
            >+</button>
            <button
              className="w-8 h-8 bg-clay-700/80 hover:bg-clay-600 text-brown-100 rounded text-lg font-bold"
              onClick={() => {
                const vp = viewportRef.current;
                if (vp) vp.animate({ scale: Math.max(0.5, vp.scale.x / 1.3), time: 200 });
              }}
            >−</button>
          </div>
          {isAuthenticated && !humanPlayerId && (
              <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10">
                <button
                  className="px-6 py-3 bg-clay-700 hover:bg-clay-600 text-brown-100 rounded-lg font-display text-lg tracking-wider shadow-lg transition-colors"
                  onClick={handleJoin}
                >
                  Join Town
                </button>
              </div>
            )}
        </div>
        {/* Sidebar — fixed width */}
        <div
          className="flex flex-col overflow-y-auto shrink-0 w-80 px-4 py-6 border-l border-clay-700 bg-clay-900 text-brown-100"
          ref={scrollViewRef}
        >
          <PlayerDetails
            worldId={worldId}
            engineId={engineId}
            game={game}
            playerId={selectedElement?.id}
            setSelectedElement={setSelectedElement}
            scrollViewRef={scrollViewRef}
          />
        </div>
      </div>
    </>
  );
}
