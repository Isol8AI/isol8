import { Character } from './Character.tsx';
import { data as pixellab48Data } from '../../data/spritesheets/pixellab48';
import type { TownGameState, TownPlayer } from '../types/town';

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

  // Only render agents with a custom PixelLab sprite
  const spriteUrl = (playerDesc as any)?.spriteUrl;
  if (!spriteUrl) {
    return null;
  }
  const textureUrl = spriteUrl;
  const spritesheetData = pixellab48Data;
  const speed = 0.1;

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
