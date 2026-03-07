import closeImg from '../../assets/close.svg';
import type { TownGameState } from '../types/town';

export default function PlayerDetails({
  game,
  playerId,
  setSelectedPlayerId,
}: {
  game: TownGameState;
  playerId?: string;
  setSelectedPlayerId: (id?: string) => void;
}) {
  if (!playerId) {
    return (
      <div className="h-full text-xl flex text-center items-center p-4">
        Click on an agent on the map to see details.
      </div>
    );
  }

  const playerDesc = game.playerDescriptions.get(playerId);
  if (!playerDesc) {
    return null;
  }

  const player = game.world.players.find((p) => p.id === playerId);

  // Find recent speech bubbles from this agent
  const recentSpeech = game.speechBubbles.filter(
    (sb) => sb.speaker === playerDesc.name,
  );

  return (
    <>
      <div className="flex gap-4">
        <div className="box w-3/4 sm:w-full mr-auto">
          <h2 className="bg-brown-700 p-2 font-display text-2xl sm:text-4xl tracking-wider shadow-solid text-center">
            {playerDesc.name}
          </h2>
        </div>
        <a
          className="button text-white shadow-solid text-2xl cursor-pointer pointer-events-auto"
          onClick={() => setSelectedPlayerId(undefined)}
        >
          <h2 className="h-full bg-clay-700">
            <img className="w-4 h-4 sm:w-5 sm:h-5" src={closeImg} />
          </h2>
        </a>
      </div>

      <div className="desc my-6">
        <p className="leading-tight -m-4 bg-brown-700 text-base sm:text-sm">
          {playerDesc.description || 'An agent in GooseTown.'}
        </p>
      </div>

      {player && (
        <div className="mt-2 text-sm text-brown-400">
          Position: ({Math.round(player.position.x)}, {Math.round(player.position.y)})
          {player.speed > 0 && ' — Walking'}
        </div>
      )}

      {recentSpeech.length > 0 && (
        <div className="mt-6">
          <div className="box">
            <h2 className="bg-brown-700 text-lg text-center">Recent speech</h2>
          </div>
          <div className="chats text-base sm:text-sm mt-2">
            <div className="bg-brown-200 text-black p-2">
              {recentSpeech.map((sb, i) => (
                <div key={i} className="leading-tight mb-4">
                  <div className="flex gap-4">
                    <span className="uppercase flex-grow">{sb.speaker}</span>
                  </div>
                  <div className="bubble">
                    <p className="bg-white -mx-3 -my-1">{sb.text}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
