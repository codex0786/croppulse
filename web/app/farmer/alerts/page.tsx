"use client";

import { useEffect, useState } from "react";
import { RequireRole } from "@/components/AppShell";
import { AlertCard } from "@/components/AlertCard";
import { CachedBanner, ErrorBox, Loading } from "@/components/Status";
import { api, apiCached, type Cached } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Alert } from "@/lib/types";

function Alerts() {
  const { t } = useI18n();
  const [alerts, setAlerts] = useState<Cached<Alert[]> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const load = () => apiCached<Alert[]>("/api/v1/alerts").then(setAlerts).catch(setError);
  useEffect(() => {
    void load();
  }, []);
  if (error) return <ErrorBox error={error} />;
  if (!alerts) return <Loading />;
  return (
    <>
      <h1>{t("nav.alerts")}</h1>
      <CachedBanner fromCache={alerts.fromCache} fetchedAt={alerts.fetchedAt} />
      <p className="small muted">{t("alert.intro")}</p>
      {alerts.data.length === 0 ? <p className="card">{t("alert.none")}</p> : null}
      {alerts.data.map((a) => (
        <AlertCard key={a.id} a={a} onAck={() => api(`/api/v1/alerts/${a.id}/acknowledge`, { method: "POST" }).then(load).catch(setError)} />
      ))}
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["farmer"]}>
      <Alerts />
    </RequireRole>
  );
}
