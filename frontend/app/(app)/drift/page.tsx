import { redirect } from "next/navigation";

export default function DriftRedirect() {
  redirect("/boards?tab=drift");
}
