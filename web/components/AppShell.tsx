"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { LANGUAGES, translationReviewed, useI18n, type Lang } from "@/lib/i18n";
import { flush, pending } from "@/lib/offlineQueue";
import { homeFor, useSession } from "@/lib/session";
import type { Role } from "@/lib/types";

const NAV: Record<Role, { href: string; key: string }[]> = {
  farmer: [
    { href: "/farmer", key: "nav.home" },
    { href: "/farmer/alerts", key: "nav.alerts" },
    { href: "/farmer/fields/new", key: "nav.add_field" },
    { href: "/farmer/profile", key: "nav.profile" },
  ],
  agronomist: [
    { href: "/expert", key: "nav.cases" },
    { href: "/org", key: "nav.organisation" },
  ],
  fpo_manager: [{ href: "/org", key: "nav.organisation" }],
  regional_analyst: [{ href: "/regional", key: "nav.regional" }],
  researcher: [
    { href: "/research", key: "nav.research" },
    { href: "/regional", key: "nav.regional" },
  ],
  admin: [
    { href: "/admin", key: "nav.admin" },
    { href: "/research", key: "nav.research" },
    { href: "/regional", key: "nav.regional" },
    { href: "/expert", key: "nav.cases" },
  ],
};

export function AppShell({ children }: { children: ReactNode }) {
  const { t, lang, setLang } = useI18n();
  const { user, logout } = useSession();
  const router = useRouter();
  const path = usePathname();
  const [online, setOnline] = useState(true);
  const [queued, setQueued] = useState(0);

  useEffect(() => {
    const update = async () => {
      setOnline(navigator.onLine);
      if (navigator.onLine && pending().length) await flush();
      setQueued(pending().length);
    };
    void update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") void navigator.serviceWorker.register("/sw.js");
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  return (
    <>
      <a href="#main" className="skip">
        {t("common.skip")}
      </a>
      <header className="topbar">
        <Link href={user ? homeFor(user.role) : "/"} className="brand">
          <span aria-hidden="true">◍</span> CropPulse
        </Link>
        <nav aria-label={t("nav.main")}>
          {user
            ? NAV[user.role].map((n) => (
                <Link key={n.href} href={n.href} className={path === n.href ? "active" : ""} aria-current={path === n.href ? "page" : undefined}>
                  {t(n.key)}
                </Link>
              ))
            : null}
        </nav>
        <div className="topbar-right">
          <label className="sr-only" htmlFor="lang">
            {t("profile.language")}
          </label>
          <select id="lang" value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
          {user ? (
            <button
              type="button"
              className="link"
              onClick={() => {
                logout();
                router.push("/");
              }}
            >
              {t("nav.logout")}
            </button>
          ) : null}
        </div>
      </header>
      {!translationReviewed(lang) ? <div className="notice small">{t("i18n.unreviewed")}</div> : null}
      {!online ? <div className="warn" role="status">{t("offline.banner")}</div> : null}
      {queued > 0 ? <div className="notice small">{t("offline.queued", { n: queued })}</div> : null}
      <main id="main">{children}</main>
      <footer className="footer small muted">
        <p>{t("footer.disclaimer")}</p>
        <p>{t("footer.attribution")}</p>
      </footer>
    </>
  );
}

/** Client-side role guard (the API enforces authorisation; this only routes the UI). */
export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user, loading } = useSession();
  const router = useRouter();
  const { t } = useI18n();
  useEffect(() => {
    if (!loading && !user) router.replace("/");
  }, [loading, user, router]);
  if (loading) return <p className="muted">{t("common.loading")}</p>;
  if (!user) return null;
  if (!roles.includes(user.role)) return <p className="error">{t("common.forbidden")}</p>;
  return <>{children}</>;
}
