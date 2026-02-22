import Game from './components/Game.tsx';
import { ToastContainer } from 'react-toastify';
import { UserButton, SignedIn, SignedOut } from '@clerk/clerk-react';
import LoginButton from './components/buttons/LoginButton.tsx';
import MusicButton from './components/buttons/MusicButton.tsx';

export default function Home() {
  return (
    <main className="relative flex h-screen w-screen overflow-hidden bg-clay-900 font-body">
      {/* Full-screen game fills everything */}
      <Game />

      {/* Floating controls — top-right overlay on the map */}
      <div className="absolute top-4 right-4 z-10 flex items-center gap-3">
        <MusicButton />
        <SignedIn>
          <UserButton afterSignOutUrl="/" />
        </SignedIn>
        <SignedOut>
          <LoginButton />
        </SignedOut>
      </div>

      <ToastContainer position="bottom-right" autoClose={2000} closeOnClick theme="dark" />
    </main>
  );
}
