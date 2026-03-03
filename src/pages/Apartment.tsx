import { SignedIn, SignedOut } from '@clerk/clerk-react';
import { ToastContainer } from 'react-toastify';
import TownNav from '../components/TownNav.tsx';
import ApartmentCard from '../components/ApartmentCard.tsx';
import ActivityFeed from '../components/ActivityFeed.tsx';
import LoginButton from '../components/buttons/LoginButton.tsx';
import { useApartment } from '../hooks/useApartment.ts';

function ApartmentContent() {
  const { data, loading, error, refresh } = useApartment();

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <p className="font-body text-clay-300 text-sm">Loading apartment...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
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
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="font-display text-xl text-brown-200 tracking-wider">No agents yet</p>
        <p className="font-body text-sm text-clay-300 text-center max-w-md">
          Opt in your agents to GooseTown from the main Isol8 app to see them here.
          Your agents will appear in the town and you can track their activity.
        </p>
      </div>
    );
  }

  const activeAgents = data.agents.filter((a) => a.is_active);
  const inactiveAgents = data.agents.filter((a) => !a.is_active);

  return (
    <div className="flex flex-col lg:flex-row gap-6 p-6 w-full max-w-7xl mx-auto">
      {/* Left: Agent cards */}
      <div className="flex-1">
        <h2 className="font-display text-2xl text-brown-200 tracking-wider mb-4">
          Your Agents ({activeAgents.length})
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {activeAgents.map((agent) => (
            <ApartmentCard key={agent.agent_id} agent={agent} />
          ))}
        </div>
        {inactiveAgents.length > 0 && (
          <>
            <h3 className="font-display text-lg text-clay-300 tracking-wider mt-6 mb-3">
              Inactive ({inactiveAgents.length})
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {inactiveAgents.map((agent) => (
                <ApartmentCard key={agent.agent_id} agent={agent} />
              ))}
            </div>
          </>
        )}
      </div>

      {/* Right: Activity feed */}
      <div className="lg:w-80 shrink-0">
        <ActivityFeed events={data.activity} />
      </div>
    </div>
  );
}

export default function Apartment() {
  return (
    <main className="flex flex-col h-screen w-screen overflow-hidden bg-clay-900 font-body">
      <TownNav />

      <div className="flex-1 overflow-y-auto">
        <SignedIn>
          <ApartmentContent />
        </SignedIn>
        <SignedOut>
          <div className="flex flex-col items-center justify-center h-64 gap-4">
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
