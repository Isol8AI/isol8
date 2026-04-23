"use server";

import { auth } from "@clerk/nextjs/server";

import { listSlugVersions, type CatalogVersion } from "@/app/admin/_lib/api";

/**
 * Server Action invoked from CatalogPageClient when the operator opens the
 * VersionsPanel for a slug. Keeps the Clerk bearer token server-side — the
 * client never sees it — and returns the version history array directly so
 * the parent can thread it into the panel as a prop.
 */
export async function fetchVersions(slug: string): Promise<CatalogVersion[]> {
  const { getToken } = await auth();
  const token = (await getToken()) ?? "";
  return listSlugVersions(token, slug);
}
