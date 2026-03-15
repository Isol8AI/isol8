import { Stage, Sprite, Container } from '@pixi/react';
import { useElementSize } from 'usehooks-ts';
import { useState, useEffect } from 'react';
import { Character } from './Character.tsx';
import { characters } from '../../data/characters.ts';
import type { ApartmentAgent } from '../hooks/useApartment';

// Apartment grid: 12x8 tiles at 32px each = 384x256
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

interface Props {
  agents: ApartmentAgent[];
  lerpAgents: () => ApartmentAgent[];
}

export default function ApartmentMap({ agents, lerpAgents }: Props) {
  const [containerRef, { width, height }] = useElementSize();
  const [interpolated, setInterpolated] = useState<ApartmentAgent[]>(agents);

  // Re-interpolate positions on every animation frame for smooth movement
  useEffect(() => {
    let raf: number;
    const tick = () => {
      setInterpolated(lerpAgents());
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [lerpAgents]);

  const scale = Math.min(
    width > 0 ? width / APT_WIDTH : 1,
    height > 0 ? height / APT_HEIGHT : 1,
  );

  // Show agents in apartment context
  const apartmentAgents = interpolated.filter(
    (a) => a.location_context === 'apartment' && a.is_active,
  );

  const characterScale = (TILE_DIM / 32) * 0.8;

  return (
    <div ref={containerRef} className="w-full h-full">
      {width > 0 && height > 0 && (
        <Stage
          width={width}
          height={height}
          options={{ backgroundColor: 0x2a1f1a }}
        >
          <Container
            x={(width - APT_WIDTH * scale) / 2}
            y={(height - APT_HEIGHT * scale) / 2}
            scale={scale}
          >
            <Sprite
              image="/assets/apartment.png"
              x={0}
              y={0}
              width={APT_WIDTH}
              height={APT_HEIGHT}
            />
            {apartmentAgents.map((agent) => {
              const characterId = agent.character ?? 'c6';
              const character = characters.find((c) => c.name === characterId);
              if (!character) return null;

              return (
                <Character
                  key={agent.agent_id}
                  textureUrl={character.textureUrl}
                  spritesheetData={character.spritesheetData}
                  x={agent.position_x * TILE_DIM + TILE_DIM / 2}
                  y={agent.position_y * TILE_DIM + TILE_DIM / 2}
                  orientation={orientationDegrees(agent.facing_x, agent.facing_y)}
                  isMoving={agent.speed > 0}
                  isThinking={false}
                  isSpeaking={false}
                  isViewer={false}
                  speed={character.speed}
                  scale={characterScale}
                  onClick={() => {}}
                />
              );
            })}
          </Container>
        </Stage>
      )}
    </div>
  );
}
