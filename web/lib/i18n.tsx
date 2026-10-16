"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import en from "@/locales/en.json";
import hi from "@/locales/hi.json";
import mr from "@/locales/mr.json";

type Dict = Record<string, string>;
export type Lang = "en" | "hi" | "mr";
const DICTS: Record<Lang, Dict> = { en, hi, mr };
export const LANGUAGES: { code: Lang; label: string }[] = [
  { code: "en", label: "English" },
  { code: "mr", label: "मराठी" },
  { code: "hi", label: "हिन्दी" },
];
const LOCALES: Record<Lang, string> = { en: "en-IN", hi: "hi-IN", mr: "mr-IN" };

export function translate(lang: Lang, key: string, params?: Record<string, unknown>): string {
  const raw = DICTS[lang][key] ?? DICTS.en[key] ?? key;
  if (!params) return raw;
  return raw.replace(/\{(\w+)\}/g, (_, k) => (params[k] === undefined || params[k] === null ? "—" : String(params[k])));
}

/** Translation review status, from each locale's _meta entry. Non-English UI text is shown
 * with a visible "translation not yet reviewed" note until an agronomist/linguist approves it. */
export function translationReviewed(lang: Lang): boolean {
  return lang === "en" || DICTS[lang]["_meta.review_status"] === "reviewed";
}

interface Ctx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, params?: Record<string, unknown>) => string;
  fmtDate: (iso: string | null | undefined) => string;
  fmtNum: (n: number | null | undefined, digits?: number) => string;
}

const I18nContext = createContext<Ctx | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  useEffect(() => {
    try {
      const saved = window.localStorage.getItem("cp-lang") as Lang | null;
      if (saved && saved in DICTS) setLangState(saved);
    } catch {
      /* storage unavailable */
    }
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      window.localStorage.setItem("cp-lang", l);
    } catch {
      /* ignore */
    }
  }, []);
  const value = useMemo<Ctx>(
    () => ({
      lang,
      setLang,
      t: (key, params) => translate(lang, key, params),
      fmtDate: (iso) => {
        if (!iso) return "—";
        const d = new Date(iso.length === 10 ? `${iso}T00:00:00` : iso);
        return d.toLocaleDateString(LOCALES[lang], { day: "numeric", month: "short", year: "numeric" });
      },
      fmtNum: (n, digits = 2) => (n === null || n === undefined || Number.isNaN(n) ? "—" : n.toLocaleString(LOCALES[lang], { maximumFractionDigits: digits, minimumFractionDigits: 0 })),
    }),
    [lang, setLang],
  );
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): Ctx {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error("useI18n outside I18nProvider");
  return ctx;
}
