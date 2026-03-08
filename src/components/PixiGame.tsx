import * as PIXI from 'pixi.js';
import { useApp, PixiComponent } from '@pixi/react';
import { Player } from './Player.tsx';
import { useEffect, useRef } from 'react';
import { PixiStaticMap } from './PixiStaticMap.tsx';
import PixiViewport from './PixiViewport.tsx';
import type { TownGameState, TownPlayer } from '../types/town';

// Location labels to render on the map (hover-only)
const LOCATION_LABELS: { label: string; x: number; y: number }[] = [
  { label: 'Plaza', x: 42, y: 22 },        // area center of (32,22)→(52,34)
  { label: 'Library', x: 40, y: 11 },       // entrance point
  { label: 'Cafe', x: 10, y: 17 },          // entrance point
  { label: 'Activity Center', x: 65, y: 12 }, // entrance point
  { label: 'Residence', x: 69, y: 24 },     // spawn point / entrance
];

const HoverLabel = PixiComponent('HoverLabel', {
  create: (props: { label: string; x: number; y: number; tileDim: number }) => {
    const container = new PIXI.Container();
    const { label, x, y, tileDim } = props;

    // Invisible hit area for hover detection
    const hitArea = new PIXI.Graphics();
    hitArea.beginFill(0xffffff, 0.001);
    hitArea.drawRect(-tileDim * 2, -tileDim * 2, tileDim * 4, tileDim * 4);
    hitArea.endFill();
    hitArea.interactive = true;
    hitArea.cursor = 'pointer';
    container.addChild(hitArea);

    // Label text using the display font, hidden by default
    const text = new PIXI.Text(label, {
      fontFamily: 'Upheaval Pro',
      fontSize: 14,
      fill: '#e8d5b7',       // brown-200 tone
      stroke: '#1a1410',     // dark outline
      strokeThickness: 4,
      letterSpacing: 1,
    });
    text.anchor.set(0.5, 1);
    text.y = -tileDim * 1.2;
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
  lerpPlayers: () => TownPlayer[];
}) => {
  const pixiApp = useApp();
  const viewportRef = props.viewportRef;
  const { lerpPlayers } = props;

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

  // On first load, smoothly zoom into the Residence
  const hasAnimatedInitial = useRef(false);
  useEffect(() => {
    if (!viewportRef.current || hasAnimatedInitial.current) return;
    hasAnimatedInitial.current = true;
    // Focus on Residence spawn point (69, 24)
    const focusX = 69 * tileDim;
    const focusY = 24 * tileDim;
    viewportRef.current.animate({
      position: new PIXI.Point(focusX, focusY),
      scale: 1.5,
      time: 1500,
      ease: 'easeInOutSine',
    });
  }, [width, height, tileDim]);

  // Use lerp-interpolated positions for smooth movement
  const interpolatedPlayers = lerpPlayers();

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
      {/* Players with smooth interpolation */}
      {interpolatedPlayers.map((p) => (
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
