import { SignedIn, SignedOut } from '@clerk/clerk-react';
import { ToastContainer } from 'react-toastify';
import TownNav from '../components/TownNav.tsx';
import GameLayout from '../components/GameLayout.tsx';
import ApartmentCard from '../components/ApartmentCard.tsx';
import ApartmentMap from '../components/ApartmentMap.tsx';
import LoginButton from '../components/buttons/LoginButton.tsx';
import { useApartment, type ApartmentAgent } from '../hooks/useApartment.ts';

function ApartmentSidebar({ agents }: { agents: ApartmentAgent[] }) {
  const activeAgents = agents.filter((a) => a.is_active);
  const inactiveAgents = agents.filter((a) => !a.is_active);

  return (
    <>
      <h2 className="font-display text-lg text-brown-200 tracking-wider mb-3">
        Your Agents ({activeAgents.length})
      </h2>
      <div className="flex flex-col gap-3">
        {activeAgents.map((agent) => (
          <ApartmentCard key={agent.agent_id} agent={agent} />
        ))}
      </div>
      {inactiveAgents.length > 0 && (
        <div className="mt-4">
          <h3 className="font-display text-sm text-clay-300 tracking-wider mb-2">
            Inactive ({inactiveAgents.length})
          </h3>
          <div className="flex flex-col gap-3">
            {inactiveAgents.map((agent) => (
              <ApartmentCard key={agent.agent_id} agent={agent} />
            ))}
          </div>
        </div>
      )}
    </>
  );
}

function ApartmentContent() {
  const { data, loading, error, refresh, lerpAgents } = useApartment();

  if (loading) {
    return (
      <div className="flex items-center justify-center w-full h-full">
        <p className="font-body text-clay-300 text-sm">Loading apartment...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center w-full h-full gap-4">
        <p className="font-body text-clay-300 text-sm">{error}</p>
        <button
          onClick={() => void refresh()}
          className="button text-white shadow-solid text-sm"
        >
          <div className="inline-block bg-clay-700">
            <span>Retry</span>
          </div>
        </button>
      </div>
    );
  }

  if (!data || data.agents.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center w-full h-full gap-4">
        <p className="font-display text-xl text-brown-200 tracking-wider">No agents yet</p>
        <p className="font-body text-sm text-clay-300 text-center max-w-md">
          Opt in your agents to GooseTown from the main Isol8 app to see them here.
        </p>
      </div>
    );
  }

  return (
    <GameLayout sidebar={<ApartmentSidebar agents={data.agents} />}>
      <ApartmentMap agents={data.agents} lerpAgents={lerpAgents} />
    </GameLayout>
  );
}

export default function Apartment() {
  return (
    <main className="flex flex-col h-screen w-screen overflow-hidden bg-clay-900 font-body">
      <TownNav />

      <div className="flex-1 overflow-hidden">
        <SignedIn>
          <ApartmentContent />
        </SignedIn>
        <SignedOut>
          <div className="flex flex-col items-center justify-center h-full gap-4">
            <p className="font-display text-xl text-brown-200 tracking-wider">
              Sign in to view your apartment
            </p>
            <p className="font-body text-sm text-clay-300 mb-4">
              Log in to see your agents and their activity in GooseTown.
            </p>
            <LoginButton />
          </div>
        </SignedOut>
      </div>

      <ToastContainer position="bottom-right" autoClose={2000} closeOnClick theme="dark" />
    </main>
  );
}
