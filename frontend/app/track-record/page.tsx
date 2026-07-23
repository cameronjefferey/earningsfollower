import { redirect } from "next/navigation";

/** Half-baked public scorecard — removed from the product. */
export default function TrackRecordRedirect() {
  redirect("/brief");
}
