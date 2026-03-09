import { SignedIn, SignedOut } from '@clerk/clerk-react';
import ApartmentMap from '../components/ApartmentMap.tsx';
import LoginButton from '../components/buttons/LoginButton.tsx';
import { useApartment } from '../hooks/useApartment.ts';

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

  return <ApartmentMap agents={data.agents} lerpAgents={lerpAgents} />;
}

export default function Apartment() {
  return (
    <>
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
    </>
  );
}
