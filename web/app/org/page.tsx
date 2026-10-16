"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RequireRole } from "@/components/AppShell";
import { ErrorBox, Loading, RiskStatus } from "@/components/Status";
import { api, API_BASE, getToken } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import type { RiskState } from "@/lib/types";

interface OrgSummary {
  consenting_fields: number;
  states: Record<string, number>;
  fields: { field_id: string; field_name: string; district: string; crop: string | null; area_ha: number | null; state: RiskState | null; assessed_at: string | null; expired: boolean; escalated: boolean; vegetation_freshness: string | null; is_synthetic: boolean }[];
}

function Org() {
  const { t, fmtDate, fmtNum } = useI18n();
  const { user } = useSession();
  const [data, setData] = useState<OrgSummary | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    api<OrgSummary>("/api/v1/org/summary").then(setData).catch(setError);
  }, []);

  const download = async () => {
    const res = await fetch(`${API_BASE}/api/v1/org/export.csv`, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!res.ok) return setError(new Error(`HTTP ${res.status}`));
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = "croppulse_org_summary.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  return (
    <>
      <h1>{t("org.title")}</h1>
      <p className="small muted">{t("org.intro", { n: data.consenting_fields })}</p>
      <div className="card row">
        {Object.entries(data.states).map(([s, n]) => (
          <span key={s}>
            {s === "not_assessed" ? <span className="badge badge-muted">{t("risk.not_assessed")}</span> : <RiskStatus state={s as RiskState} />} {n}
          </span>
        ))}
      </div>
      {user?.role === "fpo_manager" ? (
        <p>
          <button type="button" className="secondary" onClick={download}>
            {t("org.export")}
          </button>{" "}
          <span className="small muted">{t("org.export_note")}</span>
        </p>
      ) : null}
      <div className="card table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t("expert.col_field")}</th>
              <th>{t("org.col_crop")}</th>
              <th>{t("expert.col_state")}</th>
              <th>{t("org.col_freshness")}</th>
              <th>{t("org.col_assessed")}</th>
            </tr>
          </thead>
          <tbody>
            {data.fields.map((f) => (
              <tr key={f.field_id}>
                <td>
                  <Link href={`/farmer/fields/${f.field_id}`}>{f.field_name}</Link>
                  <div className="small muted">
                    {f.district} · {f.area_ha ? t("unit.ha", { v: fmtNum(f.area_ha, 1) }) : "—"} {f.is_synthetic ? <span className="kind kind-synthetic">{t("kind.synthetic")}</span> : null}
                  </div>
                </td>
                <td>{f.crop ? t(`crop.${f.crop}`) : "—"}</td>
                <td>
                  <RiskStatus state={f.state} /> {f.escalated ? <span className="small">{t("org.escalated")}</span> : null}
                </td>
                <td>{f.vegetation_freshness ? t(`freshness.${f.vegetation_freshness}`) : "—"}</td>
                <td>
                  {fmtDate(f.assessed_at)} {f.expired ? <span className="small muted">({t("org.expired")})</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["fpo_manager", "agronomist"]}>
      <Org />
    </RequireRole>
  );
}
