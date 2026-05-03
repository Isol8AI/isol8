import { TeamsLayout } from "@/components/teams/TeamsLayout";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <TeamsLayout>{children}</TeamsLayout>;
}
