import { useRef, useState } from 'react';
import PixiGame from './PixiGame.tsx';
import { useElementSize } from 'usehooks-ts';
import { Stage } from '@pixi/react';
import PlayerDetails from './PlayerDetails.tsx';
import { useTownGame } from './TownProvider.tsx';

export default function Game() {
  const { game } = useTownGame();
  const [selectedPlayerId, setSelectedPlayerId] = useState<string>();
  const [gameWrapperRef, { width, height }] = useElementSize();

  const scrollViewRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<any>(null);

  if (!game) {
    return (
      <div className="flex items-center justify-center w-full h-full text-brown-300 font-body text-lg">
        Loading town...
      </div>
    );
  }

  return (
    <div className="flex w-full h-full">
      {/* Map area */}
      <div className="relative flex-1 overflow-hidden bg-brown-900 touch-none overscroll-none" ref={gameWrapperRef}>
        <div className="absolute inset-0">
          <Stage width={width} height={height} options={{ backgroundColor: 0x7ab5ff }}>
            <PixiGame
              game={game}
              width={width}
              height={height}
              setSelectedPlayerId={setSelectedPlayerId}
              viewportRef={viewportRef}
            />
          </Stage>
        </div>
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
          >−</button>
        </div>
      </div>
      {/* Sidebar */}
      <div
        className="flex flex-col overflow-y-auto shrink-0 w-80 px-4 py-6 border-l border-clay-700 bg-clay-900 text-brown-100"
        ref={scrollViewRef}
      >
        <PlayerDetails
          game={game}
          playerId={selectedPlayerId}
          setSelectedPlayerId={setSelectedPlayerId}
        />
      </div>
    </div>
  );
}
