"use client";

import { useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { captureAdAttrsFromSearch } from "@/lib/utm";

/** Persist UTMs / click ids from the current URL into sessionStorage. */
export function CaptureAdAttrs() {
  const params = useSearchParams();
  useEffect(() => {
    captureAdAttrsFromSearch(params.toString());
  }, [params]);
  return null;
}
