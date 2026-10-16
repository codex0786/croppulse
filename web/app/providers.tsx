"use client";

import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import { I18nProvider } from "@/lib/i18n";
import { SessionProvider } from "@/lib/session";

export function Providers({ children }: { children: ReactNode }) {
  return (
    <I18nProvider>
      <SessionProvider>
        <AppShell>{children}</AppShell>
      </SessionProvider>
    </I18nProvider>
  );
}
