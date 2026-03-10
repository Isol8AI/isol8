import { Stage, Sprite } from '@pixi/react';
import { useApp } from '@pixi/react';
import { useElementSize } from 'usehooks-ts';
import { useState, useEffect, useRef } from 'react';
import { Character } from './Character.tsx';
import { data as pixellab48Data } from '../../data/spritesheets/pixellab48';
import PixiViewport from './PixiViewport.tsx';
import type { ApartmentAgent } from '../hooks/useApartment';

const TILE_DIM = 32;
const GRID_WIDTH = 12;
const GRID_HEIGHT = 8;
const APT_WIDTH = GRID_WIDTH * TILE_DIM;
const APT_HEIGHT = GRID_HEIGHT * TILE_DIM;

function orientationDegrees(dx: number, dy: number): number {
  if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) {
    return 90;
  }
  const twoPi = 2 * Math.PI;
  const radians = (Math.atan2(dy, dx) + twoPi) % twoPi;
  return (radians / twoPi) * 360;
}

function ApartmentMapInner({
  agents,
  lerpAgents,
  width,
  height,
  viewportRef,
}: {
  agents: ApartmentAgent[];
  lerpAgents: () => ApartmentAgent[];
  width: number;
  height: number;
  viewportRef: React.MutableRefObject<any>;
}) {
  const pixiApp = useApp();
  const [interpolated, setInterpolated] = useState<ApartmentAgent[]>(agents);

  useEffect(() => {
    let raf: number;
    const tick = () => {
      setInterpolated(lerpAgents());
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [lerpAgents]);

  // Ctrl/Cmd + wheel = zoom
  useEffect(() => {
    const canvas = pixiApp.view as HTMLCanvasElement;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      if (!e.ctrlKey && !e.metaKey) return;
      const viewport = viewportRef.current;
      if (!viewport) return;
      const zoomFactor = e.deltaY > 0 ? 0.9 : 1.1;
      const fitScale = Math.min(width / APT_WIDTH, height / APT_HEIGHT);
      const newScale = Math.min(6.0, Math.max(fitScale, viewport.scale.x * zoomFactor));
      viewport.setZoom(newScale, true);
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [pixiApp, width, height]);

  const apartmentAgents = interpolated.filter(
    (a) => a.location_context === 'apartment' && a.is_active,
  );

  const characterScale = (TILE_DIM / 32) * 0.8;

  return (
    <PixiViewport
      app={pixiApp}
      screenWidth={width}
      screenHeight={height}
      worldWidth={APT_WIDTH}
      worldHeight={APT_HEIGHT}
      viewportRef={viewportRef}
    >
      <Sprite
        image="/assets/apartment.png"
        x={0}
        y={0}
        width={APT_WIDTH}
        height={APT_HEIGHT}
      />
      {apartmentAgents.map((agent) => {
        // Only render agents with a custom PixelLab sprite
        if (!agent.sprite_url) return null;
        const textureUrl = agent.sprite_url;
        const spritesheetData = pixellab48Data;

        return (
          <Character
            key={agent.agent_id}
            textureUrl={textureUrl}
            spritesheetData={spritesheetData}
            x={agent.position_x * TILE_DIM + TILE_DIM / 2}
            y={agent.position_y * TILE_DIM + TILE_DIM / 2}
            orientation={orientationDegrees(agent.facing_x, agent.facing_y)}
            isMoving={agent.speed > 0}
            isThinking={false}
            isSpeaking={false}
            isViewer={false}
            speed={0.1}
            scale={characterScale}
            onClick={() => {}}
          />
        );
      })}
    </PixiViewport>
  );
}

interface Props {
  agents: ApartmentAgent[];
  lerpAgents: () => ApartmentAgent[];
}

export default function ApartmentMap({ agents, lerpAgents }: Props) {
  const [containerRef, { width, height }] = useElementSize();
  const viewportRef = useRef<any>(null);

  return (
    <div ref={containerRef} className="w-full h-full relative">
      {width > 0 && height > 0 && (
        <Stage
          width={width}
          height={height}
          options={{ backgroundColor: 0x2a1f1a }}
        >
          <ApartmentMapInner
            agents={agents}
            lerpAgents={lerpAgents}
            width={width}
            height={height}
            viewportRef={viewportRef}
          />
        </Stage>
      )}
      {/* Zoom controls */}
      <div className="absolute bottom-4 right-4 z-10 flex flex-col gap-1">
        <button
          className="w-8 h-8 bg-clay-700/80 hover:bg-clay-600 text-brown-100 rounded text-lg font-bold"
          onClick={() => {
            const vp = viewportRef.current;
            if (vp) vp.animate({ scale: Math.min(6.0, vp.scale.x * 1.3), time: 200 });
          }}
        >+</button>
        <button
          className="w-8 h-8 bg-clay-700/80 hover:bg-clay-600 text-brown-100 rounded text-lg font-bold"
          onClick={() => {
            const vp = viewportRef.current;
            if (vp) vp.animate({ scale: Math.max(0.8, vp.scale.x / 1.3), time: 200 });
          }}
        >{'\u2212'}</button>
      </div>
    </div>
  );
}
