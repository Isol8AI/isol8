"use client";
import { use } from "react";
import { TeamsRouter } from "@/components/teams/TeamsRouter";

export default function TeamsSlugPage({ params }: { params: Promise<{ slug: string[] }> }) {
  const { slug } = use(params);
  return <TeamsRouter slug={slug} />;
}
