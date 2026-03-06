import * as PIXI from 'pixi.js';
import { useApp } from '@pixi/react';
import { Player, SelectElement } from './Player.tsx';
import { useEffect, useRef } from 'react';
import { PixiStaticMap } from './PixiStaticMap.tsx';
import PixiViewport from './PixiViewport.tsx';
import { Id } from '../../convex/_generated/dataModel';
import { useQuery } from 'convex/react';
import { api } from '../../convex/_generated/api.js';
import { useSendInput } from '../hooks/sendInput.ts';
import { toastOnError } from '../toasts.ts';
import { DebugPath } from './DebugPath.tsx';
import { SHOW_DEBUG_UI } from './Game.tsx';
import { ServerGame } from '../hooks/serverGame.ts';

export const PixiGame = (props: {
  worldId: Id<'worlds'>;
  engineId: Id<'engines'>;
  game: ServerGame;
  historicalTime: number | undefined;
  width: number;
  height: number;
  setSelectedElement: SelectElement;
  viewportRef: React.MutableRefObject<any>;
}) => {
  // PIXI setup.
  const pixiApp = useApp();
  const viewportRef = props.viewportRef;

  // Ctrl/Cmd + wheel = zoom (Google Maps convention)
  // Also prevent all wheel events from propagating to stop browser back/forward gestures
  useEffect(() => {
    const canvas = pixiApp.view as HTMLCanvasElement;
    const onWheel = (e: WheelEvent) => {
      // Always prevent default on the canvas to stop browser back/forward navigation
      e.preventDefault();
      if (!e.ctrlKey && !e.metaKey) return;
      const viewport = viewportRef.current;
      if (!viewport) return;
      const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
      const map = props.game.worldMap;
      const fitScale = Math.min(
        props.width / (map.width * map.tileDim),
        props.height / (map.height * map.tileDim),
      );
      const newScale = Math.min(3.0, Math.max(fitScale, viewport.scale.x * zoomFactor));
      viewport.setZoom(newScale, true);
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [pixiApp, props.width, props.height, props.game.worldMap]);

  const humanTokenIdentifier = useQuery(api.world.userStatus, { worldId: props.worldId }) ?? null;
  const humanPlayerId = [...props.game.world.players.values()].find(
    (p) => p.human === humanTokenIdentifier,
  )?.id;

  const moveTo = useSendInput(props.engineId, 'moveTo');

  // Arrow keys move the human player (hold to walk continuously)
  const keysHeld = useRef<Set<string>>(new Set());
  const moveIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!humanPlayerId) return;

    const MOVE_INTERVAL = 250; // ms between move commands while holding

    const sendMove = () => {
      if (!humanPlayerId || keysHeld.current.size === 0) return;

      const hp = props.game.world.players.get(humanPlayerId);
      if (!hp) return;

      let dx = 0, dy = 0;
      if (keysHeld.current.has('ArrowUp')) dy = -1;
      if (keysHeld.current.has('ArrowDown')) dy = 1;
      if (keysHeld.current.has('ArrowLeft')) dx = -1;
      if (keysHeld.current.has('ArrowRight')) dx = 1;
      if (dx === 0 && dy === 0) return;

      const dest = {
        x: Math.floor(hp.position.x) + dx,
        y: Math.floor(hp.position.y) + dy,
      };

      // Clamp to map bounds
      const { width, height } = props.game.worldMap;
      dest.x = Math.max(0, Math.min(width - 1, dest.x));
      dest.y = Math.max(0, Math.min(height - 1, dest.y));

      void toastOnError(moveTo({ playerId: humanPlayerId, destination: dest }));
    };

    const onKeyDown = (e: KeyboardEvent) => {
      if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) return;
      e.preventDefault();
      if (keysHeld.current.has(e.key)) return;
      keysHeld.current.add(e.key);

      sendMove();

      if (!moveIntervalRef.current) {
        moveIntervalRef.current = setInterval(sendMove, MOVE_INTERVAL);
      }
    };

    const onKeyUp = (e: KeyboardEvent) => {
      keysHeld.current.delete(e.key);
      if (keysHeld.current.size === 0 && moveIntervalRef.current) {
        clearInterval(moveIntervalRef.current);
        moveIntervalRef.current = null;
      }
    };

    window.addEventListener('keydown', onKeyDown);
    window.addEventListener('keyup', onKeyUp);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('keyup', onKeyUp);
      if (moveIntervalRef.current) clearInterval(moveIntervalRef.current);
    };
  }, [humanPlayerId, props.game]);

  const { width, height, tileDim } = props.game.worldMap;
  const players = [...props.game.world.players.values()];

  // On first load, smoothly zoom into the center of the town so observers
  // can immediately see the action.
  const hasAnimatedInitial = useRef(false);
  useEffect(() => {
    if (!viewportRef.current || hasAnimatedInitial.current) return;
    hasAnimatedInitial.current = true;
    const centerX = (width * tileDim) / 2;
    const centerY = (height * tileDim) / 2;
    viewportRef.current.animate({
      position: new PIXI.Point(centerX, centerY),
      scale: 1.5,
      time: 1500,
      ease: 'easeInOutSine',
    });
  }, [width, height, tileDim]);

  // When a human player joins, zoom to center on them
  useEffect(() => {
    if (!viewportRef.current || humanPlayerId === undefined) return;

    const humanPlayer = props.game.world.players.get(humanPlayerId)!;
    viewportRef.current.animate({
      position: new PIXI.Point(humanPlayer.position.x * tileDim, humanPlayer.position.y * tileDim),
      scale: 1.5,
      time: 800,
      ease: 'easeInOutSine',
    });
  }, [humanPlayerId]);

  return (
    <PixiViewport
      app={pixiApp}
      screenWidth={props.width}
      screenHeight={props.height}
      worldWidth={width * tileDim}
      worldHeight={height * tileDim}
      viewportRef={viewportRef}
    >
      <PixiStaticMap map={props.game.worldMap} />
      {players.map(
        (p) =>
          // Only show the path for the human player in non-debug mode.
          (SHOW_DEBUG_UI || p.id === humanPlayerId) && (
            <DebugPath key={`path-${p.id}`} player={p} tileDim={tileDim} />
          ),
      )}
      {players.map((p) => (
        <Player
          key={`player-${p.id}`}
          game={props.game}
          player={p}
          isViewer={p.id === humanPlayerId}
          onClick={props.setSelectedElement}
          historicalTime={props.historicalTime}
        />
      ))}
    </PixiViewport>
  );
};
export default PixiGame;
