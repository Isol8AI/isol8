export type ListingFormat = "openclaw" | "skillmd";
export type DeliveryMethod = "cli" | "mcp" | "both";
export type ListingStatus = "draft" | "review" | "published" | "retired" | "taken_down";

export interface Listing {
  listing_id: string;
  slug: string;
  name: string;
  description_md: string;
  format: ListingFormat;
  delivery_method: DeliveryMethod;
  price_cents: number;
  tags: string[];
  seller_id: string;
  status: ListingStatus;
  version: number;
  published_at: string | null;
  created_at: string;
}

export interface Purchase {
  purchase_id: string;
  listing_id: string;
  listing_slug: string;
  license_key: string;
  price_paid_cents: number;
  status: "paid" | "refunded" | "revoked";
  created_at: string;
}
