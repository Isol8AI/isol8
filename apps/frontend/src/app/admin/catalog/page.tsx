import { auth } from "@clerk/nextjs/server";

import { listCatalog } from "@/app/admin/_lib/api";

import { CatalogPageClient } from "./CatalogPageClient";

export const metadata = { title: "Catalog · Admin" };

export default async function CatalogPage() {
  const { getToken } = await auth();
  const token = (await getToken()) ?? "";
  const catalog = await listCatalog(token);

  return <CatalogPageClient catalog={catalog} />;
}
