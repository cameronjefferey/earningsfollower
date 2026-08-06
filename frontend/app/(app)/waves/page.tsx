import { redirect } from "next/navigation";

export default function WavesRedirect() {
  redirect("/boards?tab=waves");
}
