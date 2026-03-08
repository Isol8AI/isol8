import { Routes, Route } from 'react-router-dom';
import { SignedIn, SignedOut, UserButton } from '@clerk/clerk-react';
import { ToastContainer } from 'react-toastify';
import TownNav from './components/TownNav.tsx';
import GameLayout from './components/GameLayout.tsx';
import ApartmentCard from './components/ApartmentCard.tsx';
import LoginButton from './components/buttons/LoginButton.tsx';
import MusicButton from './components/buttons/MusicButton.tsx';
import { useApartment } from './hooks/useApartment.ts';
import Town from './pages/Town.tsx';
import Apartment from './pages/Apartment.tsx';

function AgentsSidebar() {
  const { data, loading } = useApartment();

  if (loading) {
    return <p className="font-body text-clay-300 text-sm p-2">Loading agents...</p>;
  }

  if (!data || data.agents.length === 0) {
    return (
      <SignedIn>
        <p className="font-body text-clay-300 text-sm p-2">No agents opted in yet.</p>
      </SignedIn>
    );
  }

  const activeAgents = data.agents.filter((a) => a.is_active);
  const inactiveAgents = data.agents.filter((a) => !a.is_active);

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

export default function App() {
  return (
    <main className="relative flex flex-col h-screen w-screen overflow-hidden bg-clay-900 font-body">
      <TownNav />

      <div className="relative flex-1 overflow-hidden">
        <GameLayout sidebar={<AgentsSidebar />}>
          <Routes>
            <Route path="/" element={<Town />} />
            <Route path="/apartment" element={<Apartment />} />
          </Routes>
        </GameLayout>

        {/* Floating controls -- top-right overlay on the map */}
        <div className="absolute top-4 right-4 z-10 flex items-center gap-3">
          <MusicButton />
          <SignedIn>
            <UserButton afterSignOutUrl="/" />
          </SignedIn>
          <SignedOut>
            <LoginButton />
          </SignedOut>
        </div>
      </div>

      <ToastContainer position="bottom-right" autoClose={2000} closeOnClick theme="dark" />
    </main>
  );
}
