"use client";

import { useEffect, useState } from "react";
import { RequireRole } from "@/components/AppShell";
import { ErrorBox, Loading } from "@/components/Status";
import { api } from "@/lib/api";
import { LANGUAGES, useI18n, type Lang } from "@/lib/i18n";
import { useSession } from "@/lib/session";

const OPTIONAL = ["share_with_organization", "expert_review", "aggregated_research", "notifications"];

function Profile() {
  const { t, lang, setLang } = useI18n();
  const { user, refresh } = useSession();
  const [consents, setConsents] = useState<{ policy_version: string; consents: Record<string, boolean> } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api<typeof consents>("/api/v1/me/consents").then(setConsents).catch(setError);
  }, []);

  if (!consents || !user) return <Loading />;
  return (
    <>
      <h1>{t("nav.profile")}</h1>
      <div className="card">
        <p>
          {user.display_name} · {user.email}
        </p>
        <label htmlFor="pl">{t("profile.language")}</label>
        <select
          id="pl"
          value={lang}
          onChange={async (e) => {
            const l = e.target.value as Lang;
            setLang(l);
            await api("/api/v1/me/language", { method: "PUT", body: { preferred_language: l } }).catch(setError);
            await refresh();
          }}
        >
          {LANGUAGES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>
      </div>
      <div className="card">
        <h2>{t("consent.title")}</h2>
        <p className="small">{t("consent.manage_intro", { version: consents.policy_version })}</p>
        {OPTIONAL.map((k) => (
          <label key={k} className="check">
            <input
              type="checkbox"
              checked={consents.consents[k] ?? false}
              onChange={async (e) => {
                try {
                  setConsents(await api("/api/v1/me/consents", { method: "POST", body: { purpose: k, granted: e.target.checked } }));
                } catch (err) {
                  setError(err);
                }
              }}
            />
            <span>
              <strong>{t(`consent.${k}`)}</strong>
              <br />
              <span className="small muted">{t(`consent.${k}_help`)}</span>
            </span>
          </label>
        ))}
      </div>
      <div className="card">
        <h2>{t("profile.delete_title")}</h2>
        <p className="small">{t("profile.delete_body")}</p>
        <button
          type="button"
          className="secondary"
          onClick={async () => {
            if (!window.confirm(t("profile.delete_confirm"))) return;
            await api("/api/v1/me/deletion-request", { method: "POST" }).catch(setError);
            setMsg(t("profile.delete_recorded"));
          }}
        >
          {t("profile.delete_button")}
        </button>
        {msg ? <p className="note">{msg}</p> : null}
      </div>
      <ErrorBox error={error} />
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["farmer"]}>
      <Profile />
    </RequireRole>
  );
}
