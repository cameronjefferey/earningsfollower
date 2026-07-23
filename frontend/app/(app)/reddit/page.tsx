import { redirect } from "next/navigation";

/** Distraction surface — removed from the product. */
export default function RedditRedirect() {
  redirect("/brief");
}
