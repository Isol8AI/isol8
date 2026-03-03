import Game from '../components/Game.tsx';
import { ToastContainer } from 'react-toastify';
import { UserButton, SignedIn, SignedOut } from '@clerk/clerk-react';
import LoginButton from '../components/buttons/LoginButton.tsx';
import MusicButton from '../components/buttons/MusicButton.tsx';
import TownNav from '../components/TownNav.tsx';

export default function Town() {
  return (
    <main className="relative flex flex-col h-screen w-screen overflow-hidden bg-clay-900 font-body">
      <TownNav />

      {/* Game fills remaining space */}
      <div className="relative flex-1 overflow-hidden">
        <Game />

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
