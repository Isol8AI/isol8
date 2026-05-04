import { GatewayProvider } from "@/hooks/useGateway";
import { TeamsLayout } from "@/components/teams/TeamsLayout";

export default function Layout({ children }: { children: React.ReactNode }) {
  // GatewayProvider opens the WS to API Gateway lazily — already used by /chat
  // and MyChannelsSection. /teams needs it too so TeamsEventsProvider can send
  // teams.subscribe and listen for live events.
  return (
    <GatewayProvider>
      <TeamsLayout>{children}</TeamsLayout>
    </GatewayProvider>
  );
}
