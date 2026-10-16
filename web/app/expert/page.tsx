"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RequireRole } from "@/components/AppShell";
import { CaseStatusBadge, ErrorBox, Loading, RiskStatus } from "@/components/Status";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { CaseOut } from "@/lib/types";

function Queue() {
  const { t, fmtDate } = useI18n();
  const [cases, setCases] = useState<CaseOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [filters, setFilters] = useState({ status: "", district: "", crop: "", risk_state: "", min_age_days: "" });

  useEffect(() => {
    const q = new URLSearchParams(Object.entries(filters).filter(([, v]) => v) as [string, string][]);
    api<CaseOut[]>(`/api/v1/cases?${q}`).then(setCases).catch(setError);
  }, [filters]);

  return (
    <>
      <h1>{t("expert.queue")}</h1>
      <p className="small muted">{t("expert.queue_intro")}</p>
      <div className="card row" role="search">
        {(
          [
            ["status", ["", "open", "assigned", "info_requested", "inspection_scheduled", "verified", "closed"]],
            ["risk_state", ["", "watch", "elevated_risk", "expert_review_recommended", "insufficient_evidence", "verified_stress"]],
          ] as const
        ).map(([k, opts]) => (
          <label key={k} className="small">
            {t(`expert.filter_${k}`)}
            <select value={filters[k]} onChange={(e) => setFilters({ ...filters, [k]: e.target.value })}>
              {opts.map((o) => (
                <option key={o} value={o}>
                  {o ? (k === "status" ? t(`case.${o}`) : t(`risk.${o}`)) : t("common.any")}
                </option>
              ))}
            </select>
          </label>
        ))}
        <label className="small">
          {t("expert.filter_district")}
          <input value={filters.district} onChange={(e) => setFilters({ ...filters, district: e.target.value })} />
        </label>
        <label className="small">
          {t("expert.filter_crop")}
          <input value={filters.crop} onChange={(e) => setFilters({ ...filters, crop: e.target.value })} />
        </label>
        <label className="small">
          {t("expert.filter_age")}
          <input type="number" min={0} value={filters.min_age_days} onChange={(e) => setFilters({ ...filters, min_age_days: e.target.value })} />
        </label>
      </div>
      <ErrorBox error={error} />
      {!cases ? (
        <Loading />
      ) : cases.length === 0 ? (
        <p className="card">{t("expert.no_cases")}</p>
      ) : (
        <div className="card table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("expert.col_priority")}</th>
                <th>{t("expert.col_field")}</th>
                <th>{t("expert.col_origin")}</th>
                <th>{t("expert.col_state")}</th>
                <th>{t("expert.col_status")}</th>
                <th>{t("expert.col_age")}</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.id}>
                  <td>{t(`priority.${c.priority}`)}</td>
                  <td>
                    <Link href={`/expert/cases/${c.id}`}>{c.field_name}</Link>
                    <div className="small muted">
                      {c.district} · {c.crop ? t(`crop.${c.crop}`) : "—"}
                    </div>
                  </td>
                  <td>{t(`origin.${c.origin}`)}</td>
                  <td>
                    <RiskStatus state={c.latest_state} />
                  </td>
                  <td>
                    <CaseStatusBadge status={c.status} />
                  </td>
                  <td>
                    {t("expert.days", { n: c.age_days })}
                    <div className="small muted">{fmtDate(c.created_at)}</div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["agronomist", "admin"]}>
      <Queue />
    </RequireRole>
  );
}
