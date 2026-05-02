import "./globals.css";
import { ClerkProvider } from "@clerk/nextjs";
import { UserSync } from "@/components/UserSync";

export const metadata = {
  title: "marketplace.isol8.co — AI agents you can deploy in one command",
  description: "The marketplace for AI agents. Browse, buy, deploy.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body className="bg-zinc-950 text-zinc-100">
          <UserSync />
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
