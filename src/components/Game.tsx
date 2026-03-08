import { useRef, useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import PixiGame from './PixiGame.tsx';
import { useElementSize } from 'usehooks-ts';
import { Stage } from '@pixi/react';
import { useTownGame } from './TownProvider.tsx';

export default function Game() {
  const { game, lerpPlayers } = useTownGame();
  const [selectedPlayerId, setSelectedPlayerId] = useState<string>();
  const [gameWrapperRef, { width, height }] = useElementSize();
  const [searchParams, setSearchParams] = useSearchParams();
  const [tileCoords, setTileCoords] = useState<{ x: number; y: number } | null>(null);
  const [mousePos, setMousePos] = useState<{ x: number; y: number }>({ x: 0, y: 0 });

  const viewportRef = useRef<any>(null);
  const hasFocused = useRef(false);

  // Pan to a specific agent when ?focus=<name> is in the URL
  useEffect(() => {
    const focusName = searchParams.get('focus');
    if (!focusName || !game || hasFocused.current) return;

    let matchedPlayerId: string | undefined;
    for (const [playerId, pd] of game.playerDescriptions) {
      if (pd.name === focusName) {
        matchedPlayerId = playerId;
        break;
      }
    }
    if (!matchedPlayerId) return;

    const player = game.world.players.find((p) => p.id === matchedPlayerId);
    if (!player) return;

    hasFocused.current = true;
    setSelectedPlayerId(matchedPlayerId);

    requestAnimationFrame(() => {
      const vp = viewportRef.current;
      if (!vp) return;
      const { tileDim } = game.worldMap;
      vp.animate({
        position: { x: player.position.x * tileDim, y: player.position.y * tileDim },
        scale: 2.0,
        time: 800,
        ease: 'easeInOutSine',
      });
    });

    setSearchParams({}, { replace: true });
  }, [searchParams, game, setSearchParams]);

  // Convert screen mouse position to tile coordinates via the viewport transform
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const vp = viewportRef.current;
      if (!vp || !game) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const screenX = e.clientX - rect.left;
      const screenY = e.clientY - rect.top;
      setMousePos({ x: e.clientX, y: e.clientY });
      // Transform screen coords to world coords using viewport
      const worldX = (screenX - vp.x) / vp.scale.x;
      const worldY = (screenY - vp.y) / vp.scale.y;
      const tileX = Math.floor(worldX / game.worldMap.tileDim);
      const tileY = Math.floor(worldY / game.worldMap.tileDim);
      setTileCoords({ x: tileX, y: tileY });
    },
    [game],
  );

  if (!game) {
    return (
      <div className="flex items-center justify-center w-full h-full text-brown-300 font-body text-lg">
        Loading town...
      </div>
    );
  }

  return (
    <>
      <div
        className="absolute inset-0"
        ref={gameWrapperRef}
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setTileCoords(null)}
      >
        <Stage width={width} height={height} options={{ backgroundColor: 0x7ab5ff }}>
          <PixiGame
            game={game}
            width={width}
            height={height}
            setSelectedPlayerId={setSelectedPlayerId}
            viewportRef={viewportRef}
            lerpPlayers={lerpPlayers}
          />
        </Stage>
      </div>
      {/* Tile coordinate overlay */}
      {tileCoords && (
        <div
          className="fixed z-50 pointer-events-none bg-black/80 text-white text-xs font-mono px-2 py-1 rounded"
          style={{ left: mousePos.x + 16, top: mousePos.y - 8 }}
        >
          ({tileCoords.x}, {tileCoords.y})
        </div>
      )}
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
            if (vp) vp.animate({ scale: Math.max(0.8, vp.scale.x / 1.3), time: 200 });
          }}
        >-</button>
      </div>
    </>
  );
}
