import { ReactNode } from 'react';
import { ClerkProvider, useAuth } from '@clerk/clerk-react';
import { ConvexReactClient, ConvexProvider, ConvexProviderWithClerk } from 'convex/react';

const CLERK_PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string;

// The ConvexReactClient shim reads VITE_BACKEND_URL internally.
// The constructor URL arg is ignored — kept only for API compat.
const convex = new ConvexReactClient('unused');

export default function ConvexClientProvider({ children }: { children: ReactNode }) {
  if (!CLERK_PUBLISHABLE_KEY) {
    // Fallback: render without auth (spectator-only mode).
    return <ConvexProvider client={convex}>{children}</ConvexProvider>;
  }

  return (
    <ClerkProvider publishableKey={CLERK_PUBLISHABLE_KEY}>
      <ConvexProviderWithClerk client={convex} useAuth={useAuth}>
        {children}
      </ConvexProviderWithClerk>
    </ClerkProvider>
  );
}
