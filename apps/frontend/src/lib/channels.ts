/**
 * Shared constants for the multi-user channels UI.
 *
 * Used by AgentChannelsSection (admin per-agent), MyChannelsSection
 * (per-member settings), BotSetupWizard, and the ProvisioningStepper
 * onboarding flow. All four surfaces should agree on the supported
 * provider list and human-readable labels.
 */

export type Provider = "telegram" | "discord" | "slack";

export const PROVIDERS: Provider[] = ["telegram", "discord", "slack"];

export const PROVIDER_LABELS: Record<Provider, string> = {
  telegram: "Telegram",
  discord: "Discord",
  slack: "Slack",
};

/**
 * Username conventions per provider. Telegram traditionally prefixes bot
 * handles with "@"; Discord and Slack do not. Used to render bot names
 * consistently across the channels UI.
 */
export function formatBotHandle(provider: Provider, username: string): string {
  return provider === "telegram" ? `@${username}` : username;
}
