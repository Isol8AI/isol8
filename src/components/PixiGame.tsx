import * as PIXI from 'pixi.js';
import { useApp, Container, PixiComponent } from '@pixi/react';
import { Player } from './Player.tsx';
import { useEffect, useRef, useState } from 'react';
import { TiledMapRenderer, type MapDimensions } from './TiledMapRenderer.tsx';
import PixiViewport from './PixiViewport.tsx';
import type { TownGameState, TownPlayer } from '../types/town';

// Location labels to render on the map (hover-only)
const LOCATION_LABELS: { label: string; x: number; y: number }[] = [
  { label: 'Plaza', x: 34, y: 22 },
  { label: 'Library', x: 36, y: 12 },
  { label: 'Cafe', x: 16, y: 14 },
  { label: 'Activity Center', x: 48, y: 12 },
  { label: 'Residence', x: 42, y: 36 },
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

    // Label group (background box + text), hidden by default
    const labelGroup = new PIXI.Container();
    labelGroup.visible = false;

    const text = new PIXI.Text(label, {
      fontFamily: 'Upheaval Pro',
      fontSize: 14,
      fill: '#1a1410',
      letterSpacing: 1,
    });
    text.anchor.set(0.5, 0.5);

    // White rounded box behind text
    const padX = 8;
    const padY = 4;
    const bg = new PIXI.Graphics();
    bg.beginFill(0xffffff, 0.92);
    bg.drawRoundedRect(
      -text.width / 2 - padX,
      -text.height / 2 - padY,
      text.width + padX * 2,
      text.height + padY * 2,
      4,
    );
    bg.endFill();

    labelGroup.addChild(bg);
    labelGroup.addChild(text);
    labelGroup.y = -tileDim * 1.5;
    container.addChild(labelGroup);

    hitArea.on('pointerover', () => { labelGroup.visible = true; });
    hitArea.on('pointerout', () => { labelGroup.visible = false; });

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
  const [mapDims, setMapDims] = useState<MapDimensions | null>(null);

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
    // Focus on central plaza
    const focusX = 34 * tileDim;
    const focusY = 22 * tileDim;
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
      {/* Ground layers (below agents) */}
      <TiledMapRenderer
        mapUrl="/assets/town-v2-map.tmj"
        tilesetUrl="/assets/tilesets/town-v2-tileset.png"
        layers={['Ground_Base', 'Ground_Detail', 'Water_Back', 'Terrain_Structures', 'Buildings_Base', 'Props_Back', 'Animation_Back']}
        onMapLoaded={setMapDims}
      />
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
      {/* Players with smooth interpolation, Y-sorted */}
      <Container sortableChildren={true}>
        {interpolatedPlayers.map((p) => (
          <Player
            key={`player-${p.id}`}
            game={props.game}
            player={p}
            onClick={(id) => props.setSelectedPlayerId(id)}
            tileDim={tileDim}
          />
        ))}
      </Container>
      {/* Foreground layers (above agents) */}
      <TiledMapRenderer
        mapUrl="/assets/town-v2-map.tmj"
        tilesetUrl="/assets/tilesets/town-v2-tileset.png"
        layers={['Props_Front', 'Foreground_Low', 'Foreground_High']}
      />
    </PixiViewport>
  );
};
export default PixiGame;
