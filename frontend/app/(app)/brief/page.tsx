import { redirect } from "next/navigation";

/** Brief folded into Calendar's Today strip — no standalone page. */
export default function BriefRedirect() {
  redirect("/calendar");
}
