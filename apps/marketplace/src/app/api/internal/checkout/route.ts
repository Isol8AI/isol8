import { NextRequest, NextResponse } from "next/server";
import { checkout } from "@/lib/api";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const origin = new URL(req.url).origin;
  try {
    const result = await checkout({
      listingSlug: body.listing_slug,
      successUrl: `${origin}/buyer?success=true`,
      cancelUrl: `${origin}/listing/${body.listing_slug}`,
      jwt: body.jwt,
      email: body.email,
    });
    return NextResponse.json(result);
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "checkout failed" },
      { status: 500 }
    );
  }
}
