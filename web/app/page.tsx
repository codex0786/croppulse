"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ErrorBox } from "@/components/Status";
import { useI18n } from "@/lib/i18n";
import { homeFor, useSession } from "@/lib/session";

export default function LoginPage() {
  const { t } = useI18n();
  const { user, login } = useSession();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (user) router.replace(homeFor(user.role));
  }, [user, router]);

  return (
    <>
      <h1>{t("login.title")}</h1>
      <p className="muted">{t("login.intro")}</p>
      <form
        className="card"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            const me = await login(email, password);
            router.push(homeFor(me.role));
          } catch (err) {
            setError(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label htmlFor="email">{t("login.email")}</label>
        <input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <label htmlFor="password">{t("login.password")}</label>
        <input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <ErrorBox error={error} />
        <p>
          <button type="submit" disabled={busy}>
            {busy ? t("common.working") : t("login.submit")}
          </button>
        </p>
        <p className="small">
          {t("login.no_account")} <Link href="/register">{t("login.register")}</Link>
        </p>
      </form>
      <div className="card small">
        <h2>{t("about.title")}</h2>
        <p>{t("about.body1")}</p>
        <p>{t("about.body2")}</p>
      </div>
    </>
  );
}
