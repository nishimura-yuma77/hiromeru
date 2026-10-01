"use client";

import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { makeQueryClient } from "@/shared/api/queryClient";

let browserClient: QueryClient | undefined;

export function QueryProvider({ children }: { children: ReactNode }) {
  const client = typeof window === "undefined" ? makeQueryClient() : (browserClient ??= makeQueryClient());
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
