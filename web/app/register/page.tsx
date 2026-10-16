"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorBox } from "@/components/Status";
import { api } from "@/lib/api";
import { LANGUAGES, useI18n, type Lang } from "@/lib/i18n";
import { useSession } from "@/lib/session";

export default function RegisterPage() {
  const { t, lang, setLang } = useI18n();
  const { login } = useSession();
  const router = useRouter();
  const [form, setForm] = useState({ display_name: "", email: "", password: "", organization_id: "" });
  const [consents, setConsents] = useState({ expert_review: false, share_with_organization: false, aggregated_research: false, notifications: false });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  return (
    <>
      <h1>{t("register.title")}</h1>
      <form
        className="card"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await api("/api/v1/auth/register", {
              method: "POST",
              body: { ...form, organization_id: form.organization_id || null, preferred_language: lang },
            });
            await login(form.email, form.password);
            for (const [purpose, granted] of Object.entries(consents)) {
              if (granted) await api("/api/v1/me/consents", { method: "POST", body: { purpose, granted } });
            }
            router.push("/farmer/fields/new");
          } catch (err) {
            setError(err);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label htmlFor="lang-reg">{t("register.language")}</label>
        <select id="lang-reg" value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
          {LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>
        <label htmlFor="name">{t("register.name")}</label>
        <input id="name" required maxLength={120} value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
        <label htmlFor="email">{t("login.email")}</label>
        <input id="email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <label htmlFor="pw">{t("register.password")}</label>
        <input id="pw" type="password" minLength={10} required autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <label htmlFor="org">{t("register.org_code")}</label>
        <input id="org" value={form.organization_id} onChange={(e) => setForm({ ...form, organization_id: e.target.value.trim() })} aria-describedby="org-help" />
        <p id="org-help" className="small muted">
          {t("register.org_help")}
        </p>
        <fieldset>
          <legend>{t("consent.title")}</legend>
          <p className="small">{t("consent.intro")}</p>
          {(Object.keys(consents) as (keyof typeof consents)[]).map((k) => (
            <label key={k} className="check">
              <input type="checkbox" checked={consents[k]} onChange={(e) => setConsents({ ...consents, [k]: e.target.checked })} />
              <span>
                <strong>{t(`consent.${k}`)}</strong>
                <br />
                <span className="small muted">{t(`consent.${k}_help`)}</span>
              </span>
            </label>
          ))}
          <p className="small muted">{t("consent.withdraw")}</p>
        </fieldset>
        <ErrorBox error={error} />
        <button type="submit" disabled={busy}>
          {busy ? t("common.working") : t("register.submit")}
        </button>
      </form>
    </>
  );
}
