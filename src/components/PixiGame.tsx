import * as PIXI from 'pixi.js';
import { useApp, PixiComponent } from '@pixi/react';
import { Player } from './Player.tsx';
import { useEffect, useRef } from 'react';
import { PixiStaticMap } from './PixiStaticMap.tsx';
import PixiViewport from './PixiViewport.tsx';
import type { TownGameState } from '../types/town';
import { useTownGame } from './TownProvider.tsx';

// Location labels to render on the map (hover-only)
const LOCATION_LABELS: { label: string; x: number; y: number }[] = [
  { label: 'Town Plaza', x: 49, y: 33 },
  { label: 'Cafe', x: 32, y: 34 },
  { label: 'Library', x: 38, y: 21 },
  { label: 'Town Hall', x: 62, y: 28 },
  { label: 'Apartment', x: 37, y: 41 },
  { label: 'Barn', x: 60, y: 36 },
  { label: 'Shop', x: 47, y: 48 },
  { label: 'Residential', x: 53, y: 40 },
];

const HoverLabel = PixiComponent('HoverLabel', {
  create: (props: { label: string; x: number; y: number; tileDim: number }) => {
    const container = new PIXI.Container();
    const { label, x, y, tileDim } = props;

    // Invisible hit area for hover detection
    const hitArea = new PIXI.Graphics();
    hitArea.beginFill(0xffffff, 0.001);
    hitArea.drawRect(-tileDim * 1.5, -tileDim * 1.5, tileDim * 3, tileDim * 3);
    hitArea.endFill();
    hitArea.interactive = true;
    hitArea.cursor = 'pointer';
    container.addChild(hitArea);

    // Label text, hidden by default
    const text = new PIXI.Text(label, {
      fontFamily: 'Arial',
      fontSize: 11,
      fill: '#ffffff',
      stroke: '#000000',
      strokeThickness: 3,
      fontWeight: 'bold',
    });
    text.anchor.set(0.5, 1);
    text.y = -tileDim * 0.8;
    text.visible = false;
    container.addChild(text);

    hitArea.on('pointerover', () => { text.visible = true; });
    hitArea.on('pointerout', () => { text.visible = false; });

    container.x = x * tileDim + tileDim / 2;
    container.y = y * tileDim + tileDim / 2;

    return container;
  },
  applyProps: () => {},
});

export const PixiGame = (props: {
  game: TownGameState;
  width: number;
  height: number;
  setSelectedPlayerId: (id?: string) => void;
  viewportRef: React.MutableRefObject<any>;
}) => {
  const pixiApp = useApp();
  const viewportRef = props.viewportRef;
  const { lerpPlayers } = useTownGame();

  // Ctrl/Cmd + wheel = zoom
  useEffect(() => {
    const canvas = pixiApp.view as HTMLCanvasElement;
    const onWheel = (e: WheelEvent) => {
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

  const { width, height, tileDim } = props.game.worldMap;

  // On first load, smoothly zoom into the center of the town
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

  // Use lerp-interpolated positions for smooth movement
  const interpolatedPlayers = lerpPlayers();

  // Debug: log player counts to diagnose rendering
  console.log('[PixiGame] game.world.players:', props.game.world.players.length, 'lerp:', interpolatedPlayers.length);

  // Use game.world.players directly as fallback if lerp is empty
  const playersToRender = interpolatedPlayers.length > 0
    ? interpolatedPlayers
    : props.game.world.players;

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
      {/* Location labels (hover-only) */}
      {LOCATION_LABELS.map((loc) => (
        <HoverLabel
          key={loc.label}
          label={loc.label}
          x={loc.x}
          y={loc.y}
          tileDim={tileDim}
        />
      ))}
      {/* Players */}
      {playersToRender.map((p) => (
        <Player
          key={`player-${p.id}`}
          game={props.game}
          player={p}
          onClick={(id) => props.setSelectedPlayerId(id)}
          tileDim={tileDim}
        />
      ))}
    </PixiViewport>
  );
};
export default PixiGame;
