import { redirect } from "next/navigation";

/** Reddit trading surface removed - send leftovers to Calendar. */
export default function RedditRedirect() {
  redirect("/calendar");
}
