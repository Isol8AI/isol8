import { ReactNode } from 'react';
import { ConvexReactClient, ConvexProvider } from 'convex/react';

// The ConvexReactClient shim reads VITE_BACKEND_URL internally.
// The constructor URL arg is ignored — kept only for API compat.
const convex = new ConvexReactClient('unused');

export default function ConvexClientProvider({ children }: { children: ReactNode }) {
  return <ConvexProvider client={convex}>{children}</ConvexProvider>;
}
