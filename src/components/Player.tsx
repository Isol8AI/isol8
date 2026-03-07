import { Character } from './Character.tsx';
import { characters } from '../../data/characters.ts';
import { toast } from 'react-toastify';
import type { TownGameState, TownPlayer } from '../types/town';
import { Graphics } from '@pixi/react';
import * as PIXI from 'pixi.js';
import { useCallback } from 'react';

const logged = new Set<string>();

function orientationDegrees(dx: number, dy: number): number {
  if (Math.abs(dx) < 0.001 && Math.abs(dy) < 0.001) {
    return 90; // default: face down
  }
  const twoPi = 2 * Math.PI;
  const radians = (Math.atan2(dy, dx) + twoPi) % twoPi;
  return (radians / twoPi) * 360;
}

export const Player = ({
  game,
  player,
  onClick,
  tileDim,
}: {
  game: TownGameState;
  player: TownPlayer;
  onClick: (playerId: string) => void;
  tileDim: number;
}) => {
  const playerDesc = game.playerDescriptions.get(player.id);
  const characterId = playerDesc?.character ?? 'c6';
  const character = characters.find((c) => c.name === characterId);

  if (!character) {
    if (!logged.has(characterId)) {
      logged.add(characterId);
      toast.error(`Unknown character ${characterId}`);
    }
    return null;
  }

  const isSpeaking = game.speechBubbles.some(
    (sb) => sb.speaker === playerDesc?.name,
  );

  // Scale up characters to match the chunky pixel art map style
  const characterScale = (tileDim / 32) * 2.5;
  const px = player.position.x * tileDim + tileDim / 2;
  const py = player.position.y * tileDim + tileDim / 2;

  // Debug marker — bright red circle at agent position
  const drawDebug = useCallback((g: PIXI.Graphics) => {
    g.clear();
    g.beginFill(0xff0000);
    g.drawCircle(0, 0, tileDim);
    g.endFill();
  }, [tileDim]);

  return (
    <>
      <Graphics draw={drawDebug} x={px} y={py} />
      <Character
        x={px}
        y={py}
        orientation={orientationDegrees(player.facing.dx, player.facing.dy)}
        isMoving={player.speed > 0}
        isThinking={false}
        isSpeaking={isSpeaking}
        isViewer={false}
        textureUrl={character.textureUrl}
        spritesheetData={character.spritesheetData}
        speed={character.speed}
        scale={characterScale}
        onClick={() => onClick(player.id)}
      />
    </>
  );
};
