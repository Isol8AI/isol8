/**
 * Centralized PostHog event capture helper.
 *
 * All product event instrumentation must go through `capture()` so the
 * SSR + "PostHog not loaded" guards live in exactly one place. Call sites
 * stay readable: just `capture("agent_created", { agent_id })`.
 *
 * The union type `AnalyticsEvent` acts as a registry of every product
 * event we emit. Adding a new event? Add it here first — TypeScript will
 * flag every call site that needs to be updated.
 *
 * What belongs here:
 *   - User intents (chat_message_sent, subscription_checkout_started)
 *   - User-visible outcomes (chat_completed, channel_link_submitted)
 *
 * What does NOT belong here:
 *   - RPC-call-level events (backend HTTP activity goes to CloudWatch —
 *     don't shadow it in PostHog)
 *   - PII beyond identify-level fields (specifically: no message content,
 *     no bot tokens, no API key values — capture lengths / types only)
 */

import posthog from "posthog-js";

export type AnalyticsEvent =
  | "agent_created"
  | "agent_deleted"
  | "chat_message_sent"
  | "chat_completed"
  | "chat_aborted"
  | "subscription_checkout_started"
  | "channel_link_submitted"
  | "onboarding_step_completed"
  | "catalog_agent_deployed"
  | "catalog_agent_published";

/**
 * Type exposing the `__loaded` flag PostHog sets after `init()` resolves.
 * Declared locally so we don't have to import a private type — the field
 * is part of the public contract (documented at
 * https://posthog.com/docs/libraries/js).
 */
interface PostHogLoadState {
  __loaded?: boolean;
}

function isLoaded(): boolean {
  return (posthog as unknown as PostHogLoadState).__loaded === true;
}

/**
 * Capture a product event. Safe to call from hooks/components that may
 * render during SSR (returns early without touching PostHog) and from
 * environments where NEXT_PUBLIC_POSTHOG_KEY is unset (returns early
 * because `init()` was never called and `__loaded` is false).
 */
export function capture(
  event: AnalyticsEvent,
  properties?: Record<string, unknown>,
): void {
  if (typeof window === "undefined") return;
  if (!isLoaded()) return;
  posthog.capture(event, properties);
}

/**
 * Forward an unhandled browser error to PostHog's error tracking. Used by
 * the global error/unhandledrejection forwarders installed in
 * PostHogProvider. Kept in this module so the SSR + "not loaded" guards
 * stay co-located with `capture()`.
 */
export function captureException(error: unknown): void {
  if (typeof window === "undefined") return;
  if (!isLoaded()) return;
  // posthog-js >= 1.190 exposes captureException directly.
  posthog.captureException(error);
}
