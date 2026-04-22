import Link from "next/link";

/**
 * Rendered when the admin layout's `/admin/me` probe returns non-admin.
 * Intentionally minimal — no admin UI chrome, no surface area for probing.
 */
export default function NotAuthorizedPage() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <h1 className="text-2xl font-semibold text-zinc-100">403 — Not authorized</h1>
      <p className="max-w-md text-zinc-400">You are not a platform admin.</p>
      <Link
        href="/"
        className="rounded-md border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-800"
      >
        Back to home
      </Link>
    </div>
  );
}
