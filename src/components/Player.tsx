import { Character } from './Character.tsx';
import { characters } from '../../data/characters.ts';
import { data as pixellab48Data } from '../../data/spritesheets/pixellab48';
import { toast } from 'react-toastify';
import type { TownGameState, TownPlayer } from '../types/town';

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

  // Use custom sprite URL if available, otherwise fall back to bundled character
  const spriteUrl = (playerDesc as any)?.spriteUrl;
  const textureUrl = spriteUrl || character?.textureUrl;
  const spritesheetData = spriteUrl ? pixellab48Data : (character?.spritesheetData ?? pixellab48Data);
  const speed = character?.speed ?? 0.1;

  if (!textureUrl) {
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

  return (
    <Character
      x={player.position.x * tileDim + tileDim / 2}
      y={player.position.y * tileDim + tileDim / 2}
      orientation={orientationDegrees(player.facing.dx, player.facing.dy)}
      isMoving={player.speed > 0}
      isThinking={false}
      isSpeaking={isSpeaking}
      isViewer={false}
      textureUrl={textureUrl}
      spritesheetData={spritesheetData}
      speed={speed}
      scale={characterScale}
      onClick={() => onClick(player.id)}
    />
  );
};
