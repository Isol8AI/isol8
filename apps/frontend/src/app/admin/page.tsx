import { redirect } from "next/navigation";

/**
 * `/admin` is just a default landing — funnel everyone to the user directory
 * (the most common entry point).
 */
export default function AdminIndexPage() {
  redirect("/admin/users");
}
