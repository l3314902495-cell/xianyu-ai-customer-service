"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { ConfirmProvider } from "@/components/confirm-dialog";
import { ToastProvider } from "@/components/toast";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 4000, retry: 1 } } }));
  return <QueryClientProvider client={client}><ToastProvider><ConfirmProvider>{children}</ConfirmProvider></ToastProvider></QueryClientProvider>;
}
