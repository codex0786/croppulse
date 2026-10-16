"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RequireRole } from "@/components/AppShell";
import { CachedBanner, ErrorBox, Loading, RiskStatus } from "@/components/Status";
import { api, apiCached, type Cached } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Alert, FieldSummary } from "@/lib/types";

interface Advisory {
  id: string;
  source_org: string;
  source_url: string;
  title: string;
  body: string;
  issued_at: string;
  valid_until: string;
  districts: string[];
}

function FarmerHome() {
  const { t, fmtDate, fmtNum } = useI18n();
  const [fields, setFields] = useState<Cached<FieldSummary[]> | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [advisories, setAdvisories] = useState<Advisory[]>([]);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    apiCached<FieldSummary[]>("/api/v1/fields").then(setFields).catch(setError);
    api<Alert[]>("/api/v1/alerts").then(setAlerts).catch(() => setAlerts([]));
    api<Advisory[]>("/api/v1/advisories").then(setAdvisories).catch(() => setAdvisories([]));
  }, []);

  return (
    <>
      <div className="spread">
        <h1>{t("farmer.my_fields")}</h1>
        <Link className="btn" href="/farmer/fields/new">
          + {t("nav.add_field")}
        </Link>
      </div>
      <ErrorBox error={error} />
      {fields ? <CachedBanner fromCache={fields.fromCache} fetchedAt={fields.fetchedAt} /> : null}
      {alerts.length ? (
        <div className="card">
          <h2>{t("farmer.active_alerts", { n: alerts.length })}</h2>
          <Link href="/farmer/alerts">{t("farmer.view_alerts")}</Link>
        </div>
      ) : null}
      {!fields ? (
        <Loading />
      ) : fields.data.length === 0 ? (
        <div className="card">
          <p>{t("farmer.no_fields")}</p>
          <Link href="/farmer/fields/new">{t("farmer.register_first")}</Link>
        </div>
      ) : (
        <ul className="list card">
          {fields.data.map((f) => (
            <li key={f.id}>
              <div className="spread">
                <div>
                  <Link href={`/farmer/fields/${f.id}`}>
                    <strong>{f.name}</strong>
                  </Link>
                  <div className="small muted">
                    {f.district} · {f.crop ? t(`crop.${f.crop}`) : "—"} · {f.season ? t(`season.${f.season}`) : ""} · {f.area_ha ? t("unit.ha", { v: fmtNum(f.area_ha, 1) }) : t("field.point_only")}
                  </div>
                  {f.is_synthetic ? <span className="kind kind-synthetic">{t("kind.synthetic")}</span> : null}
                </div>
                <div style={{ textAlign: "right" }}>
                  <RiskStatus state={f.latest_state} />
                  <div className="small muted">{f.latest_assessed_at ? t("farmer.assessed_on", { date: fmtDate(f.latest_assessed_at) }) : t("farmer.not_yet_assessed")}</div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      <div className="card">
        <h2>{t("advisory.title")}</h2>
        {advisories.length === 0 ? (
          <p className="small muted">{t("advisory.none")}</p>
        ) : (
          <ul className="list">
            {advisories.map((a) => (
              <li key={a.id}>
                <strong>{a.title}</strong>
                <p>{a.body}</p>
                <p className="small muted">
                  {t("advisory.meta", { org: a.source_org, issued: fmtDate(a.issued_at), until: fmtDate(a.valid_until) })} ·{" "}
                  <a href={a.source_url} target="_blank" rel="noopener noreferrer">
                    {t("advisory.official_source")}
                  </a>
                </p>
              </li>
            ))}
          </ul>
        )}
        <p className="small muted">{t("advisory.manual_note")}</p>
      </div>
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["farmer"]}>
      <FarmerHome />
    </RequireRole>
  );
}
