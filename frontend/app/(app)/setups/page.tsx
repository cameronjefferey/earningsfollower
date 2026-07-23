import { redirect } from "next/navigation";

/** Folded into Brief — keep URL from breaking old links. */
export default function SetupsRedirect() {
  redirect("/brief");
}
