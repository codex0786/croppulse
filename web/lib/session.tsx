"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, clearLocalData, getToken, setToken } from "@/lib/api";
import type { User } from "@/lib/types";
import { useI18n, type Lang } from "@/lib/i18n";

interface SessionCtx {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const Ctx = createContext<SessionCtx | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const { setLang } = useI18n();

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api<User>("/api/v1/auth/me");
      setUser(me);
      if (["en", "hi", "mr"].includes(me.preferred_language)) setLang(me.preferred_language as Lang);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [setLang]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const login = useCallback(
    async (email: string, password: string) => {
      const tok = await api<{ access_token: string }>("/api/v1/auth/login", { method: "POST", body: { email, password } });
      setToken(tok.access_token);
      const me = await api<User>("/api/v1/auth/me");
      setUser(me);
      if (["en", "hi", "mr"].includes(me.preferred_language)) setLang(me.preferred_language as Lang);
      return me;
    },
    [setLang],
  );

  const logout = useCallback(() => {
    clearLocalData();
    setUser(null);
  }, []);

  return <Ctx.Provider value={{ user, loading, login, logout, refresh }}>{children}</Ctx.Provider>;
}

export function useSession(): SessionCtx {
  const c = useContext(Ctx);
  if (!c) throw new Error("useSession outside SessionProvider");
  return c;
}

export function homeFor(role: string): string {
  switch (role) {
    case "farmer":
      return "/farmer";
    case "agronomist":
      return "/expert";
    case "fpo_manager":
      return "/org";
    case "regional_analyst":
      return "/regional";
    case "researcher":
      return "/research";
    case "admin":
      return "/admin";
    default:
      return "/";
  }
}
