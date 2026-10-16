"use client";

import { useEffect, useState } from "react";
import { RequireRole } from "@/components/AppShell";
import { ErrorBox, Loading } from "@/components/Status";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

interface Job {
  id: string;
  source_id: string;
  job_type: string;
  target_ref: string | null;
  status: string;
  started_at: string;
  finished_at: string | null;
  records_written: number;
  records_unchanged: number;
  records_rejected: number;
  warnings: string[];
  message: string | null;
}

function Admin() {
  const { t, fmtDate } = useI18n();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [metrics, setMetrics] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [adv, setAdv] = useState({ source_org: "IMD", source_url: "https://mausam.imd.gov.in/", kind: "heat_warning", title: "", body: "", districts: "", issued_at: "", valid_until: "" });

  useEffect(() => {
    api<Job[]>("/api/v1/admin/jobs").then(setJobs).catch(setError);
    api<Record<string, unknown>>("/api/v1/admin/metrics").then(setMetrics).catch(setError);
  }, []);

  return (
    <>
      <h1>{t("admin.title")}</h1>
      <ErrorBox error={error} />
      <section className="card">
        <h2>{t("admin.add_advisory")}</h2>
        <p className="small muted">{t("admin.advisory_note")}</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api("/api/v1/admin/advisories", {
                method: "POST",
                body: { ...adv, districts: adv.districts.split(",").map((d) => d.trim()).filter(Boolean), issued_at: new Date(adv.issued_at).toISOString(), valid_until: new Date(adv.valid_until).toISOString() },
              });
              setMsg(t("admin.advisory_saved"));
            } catch (err) {
              setError(err);
            }
          }}
        >
          <div className="grid2">
            <div>
              <label htmlFor="so">{t("admin.source_org")}</label>
              <select id="so" value={adv.source_org} onChange={(e) => setAdv({ ...adv, source_org: e.target.value })}>
                {["IMD", "State Agriculture Department", "KVK", "Other official"].map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="kind">{t("admin.kind")}</label>
              <select id="kind" value={adv.kind} onChange={(e) => setAdv({ ...adv, kind: e.target.value })}>
                {["heat_warning", "heavy_rain", "agromet", "other"].map((o) => (
                  <option key={o} value={o}>
                    {t(`advisory_kind.${o}`)}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <label htmlFor="url">{t("admin.source_url")}</label>
          <input id="url" type="url" pattern="https://.*" required value={adv.source_url} onChange={(e) => setAdv({ ...adv, source_url: e.target.value })} />
          <label htmlFor="title">{t("admin.adv_title")}</label>
          <input id="title" required value={adv.title} onChange={(e) => setAdv({ ...adv, title: e.target.value })} />
          <label htmlFor="body">{t("admin.adv_body")}</label>
          <textarea id="body" required rows={3} value={adv.body} onChange={(e) => setAdv({ ...adv, body: e.target.value })} />
          <label htmlFor="d">{t("admin.districts")}</label>
          <input id="d" required value={adv.districts} onChange={(e) => setAdv({ ...adv, districts: e.target.value })} />
          <div className="grid2">
            <div>
              <label htmlFor="iss">{t("admin.issued")}</label>
              <input id="iss" type="datetime-local" required value={adv.issued_at} onChange={(e) => setAdv({ ...adv, issued_at: e.target.value })} />
            </div>
            <div>
              <label htmlFor="vu">{t("admin.valid_until")}</label>
              <input id="vu" type="datetime-local" required value={adv.valid_until} onChange={(e) => setAdv({ ...adv, valid_until: e.target.value })} />
            </div>
          </div>
          <p>
            <button type="submit">{t("common.save")}</button>
          </p>
          {msg ? <p className="note">{msg}</p> : null}
        </form>
      </section>
      <section className="card">
        <h2>{t("admin.metrics")}</h2>
        {metrics ? <pre className="small" style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(metrics, null, 2)}</pre> : <Loading />}
      </section>
      <section className="card table-wrap">
        <h2>{t("admin.jobs")}</h2>
        {!jobs ? (
          <Loading />
        ) : (
          <table>
            <thead>
              <tr>
                <th>{t("jobs.source")}</th>
                <th>{t("jobs.status")}</th>
                <th>{t("jobs.when")}</th>
                <th>{t("jobs.records")}</th>
                <th>{t("admin.warnings")}</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr key={j.id}>
                  <td>
                    {t(`source.${j.source_id}`)}
                    <div className="small muted">
                      {j.job_type} · {j.target_ref}
                    </div>
                  </td>
                  <td>
                    {t(`job.${j.status}`)}
                    {j.message ? <div className="small muted">{j.message}</div> : null}
                  </td>
                  <td className="small">{fmtDate(j.started_at)}</td>
                  <td className="small">{t("jobs.counts", { w: j.records_written, u: j.records_unchanged, r: j.records_rejected })}</td>
                  <td className="small">{j.warnings.slice(0, 3).join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["admin"]}>
      <Admin />
    </RequireRole>
  );
}
