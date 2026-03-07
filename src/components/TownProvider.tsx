import { ReactNode, createContext, useContext, useCallback } from 'react';
import { ClerkProvider, useAuth } from '@clerk/clerk-react';
import { useTownState } from '../hooks/useTownState';
import type { TownGameState, TownPlayer } from '../types/town';

const CLERK_PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string;

interface TownContextValue {
  game: TownGameState | undefined;
  lerpPlayers: () => TownPlayer[];
}

const TownContext = createContext<TownContextValue>({
  game: undefined,
  lerpPlayers: () => [],
});

export function useTownGame() {
  return useContext(TownContext);
}

function TownStateProvider({ children }: { children: ReactNode }) {
  const { getToken } = useAuth();
  const getTokenFn = useCallback(() => getToken(), [getToken]);
  const { game, lerpPlayers } = useTownState(getTokenFn);

  return (
    <TownContext.Provider value={{ game, lerpPlayers }}>
      {children}
    </TownContext.Provider>
  );
}

function UnauthTownStateProvider({ children }: { children: ReactNode }) {
  const { game, lerpPlayers } = useTownState();

  return (
    <TownContext.Provider value={{ game, lerpPlayers }}>
      {children}
    </TownContext.Provider>
  );
}

export default function TownProvider({ children }: { children: ReactNode }) {
  if (!CLERK_PUBLISHABLE_KEY) {
    return (
      <UnauthTownStateProvider>
        {children}
      </UnauthTownStateProvider>
    );
  }

  return (
    <ClerkProvider publishableKey={CLERK_PUBLISHABLE_KEY}>
      <TownStateProvider>
        {children}
      </TownStateProvider>
    </ClerkProvider>
  );
}
