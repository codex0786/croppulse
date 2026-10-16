"use client";

import { useEffect, useState } from "react";
import { RequireRole } from "@/components/AppShell";
import { ErrorBox, Loading } from "@/components/Status";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { SourceInfo } from "@/lib/types";

interface Feature {
  name: string;
  definition: string;
  units: string;
  source: string;
  availability_time: string;
  missing_behavior: string;
  leakage_risk: string;
}
interface Model {
  name: string;
  version: string;
  kind: string;
  status: string;
  intended_use: string;
  excluded_uses: string;
  created_at: string;
}
interface Evaluation {
  id: string;
  model_name: string;
  regime: string;
  is_synthetic: boolean;
  metrics: Record<string, unknown>;
  report_path: string | null;
  notes: string | null;
  created_at: string;
}

function Research() {
  const { t, fmtDate } = useI18n();
  const [sources, setSources] = useState<SourceInfo[] | null>(null);
  const [features, setFeatures] = useState<Feature[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [evals, setEvals] = useState<Evaluation[]>([]);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    api<SourceInfo[]>("/api/v1/sources").then(setSources).catch(setError);
    api<Feature[]>("/api/v1/features").then(setFeatures).catch(setError);
    api<Model[]>("/api/v1/models").then(setModels).catch(setError);
    api<Evaluation[]>("/api/v1/evaluations").then(setEvals).catch(setError);
  }, []);
  if (error) return <ErrorBox error={error} />;
  if (!sources) return <Loading />;
  return (
    <>
      <h1>{t("research.title")}</h1>
      <p className="small muted">{t("research.intro")}</p>
      <section className="card table-wrap">
        <h2>{t("research.sources")}</h2>
        <table>
          <thead>
            <tr>
              <th>{t("research.source")}</th>
              <th>{t("jobs.status")}</th>
              <th>{t("research.resolution")}</th>
              <th>{t("research.latest")}</th>
              <th>{t("research.limitations")}</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.id}>
                <td>
                  <strong>{s.name}</strong>
                  <div className="small muted">{s.provider}</div>
                  {s.documentation.map((d) => (
                    <div key={d} className="small">
                      <a href={d} target="_blank" rel="noopener noreferrer">
                        {d}
                      </a>
                    </div>
                  ))}
                </td>
                <td>
                  <span className={`badge status-${s.status}`}>{t(`source_status.${s.status}`)}</span>
                  {s.last_error ? <div className="small muted">{s.last_error.slice(0, 160)}</div> : null}
                </td>
                <td className="small">
                  {s.spatial_resolution}
                  <br />
                  {s.temporal_resolution}
                </td>
                <td className="small">
                  {s.latest_observation_end ? fmtDate(s.latest_observation_end) : "—"}
                  {s.observed_latency_days !== null ? <div>{t("research.latency", { d: s.observed_latency_days })}</div> : null}
                  {s.last_success_at ? <div className="muted">{t("research.retrieved", { date: fmtDate(s.last_success_at) })}</div> : null}
                </td>
                <td className="small">
                  <ul>
                    {s.limitations.map((l) => (
                      <li key={l}>{l}</li>
                    ))}
                  </ul>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="card">
        <h2>{t("research.models")}</h2>
        {models.length === 0 ? <p className="small muted">{t("research.no_models")}</p> : null}
        {models.map((m) => (
          <div key={`${m.name}@${m.version}`} className="guidance-item">
            <p>
              <strong>
                {m.name}@{m.version}
              </strong>{" "}
              <span className="badge">{t(`model_status.${m.status}`)}</span> <span className="small muted">{m.kind}</span>
            </p>
            <p className="small">
              <strong>{t("research.intended")}</strong> {m.intended_use}
            </p>
            <p className="small">
              <strong>{t("research.excluded")}</strong> {m.excluded_uses}
            </p>
          </div>
        ))}
      </section>
      <section className="card">
        <h2>{t("research.evaluations")}</h2>
        {evals.length === 0 ? <p className="small muted">{t("research.no_evaluations")}</p> : null}
        {evals.map((e) => (
          <details key={e.id}>
            <summary>
              {e.regime} · {e.model_name} · {fmtDate(e.created_at)} {e.is_synthetic ? <span className="kind kind-synthetic">{t("kind.synthetic")}</span> : <span className="kind">{t("research.real_data")}</span>}
            </summary>
            {e.notes ? <p className="small">{e.notes}</p> : null}
            {e.report_path ? <p className="small">{t("research.report", { path: e.report_path })}</p> : null}
            <pre className="small" style={{ whiteSpace: "pre-wrap", overflowX: "auto" }}>
              {JSON.stringify(e.metrics, null, 2)}
            </pre>
          </details>
        ))}
      </section>
      <section className="card table-wrap">
        <h2>{t("research.features")}</h2>
        <table>
          <thead>
            <tr>
              <th>{t("research.feature")}</th>
              <th>{t("research.definition")}</th>
              <th>{t("research.availability")}</th>
              <th>{t("research.missing")}</th>
              <th>{t("research.leakage")}</th>
            </tr>
          </thead>
          <tbody>
            {features.map((f) => (
              <tr key={f.name}>
                <td>
                  <code>{f.name}</code>
                  <div className="small muted">
                    {f.units} · {f.source}
                  </div>
                </td>
                <td className="small">{f.definition}</td>
                <td className="small">{f.availability_time}</td>
                <td className="small">{f.missing_behavior}</td>
                <td className="small">{f.leakage_risk}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["researcher", "admin"]}>
      <Research />
    </RequireRole>
  );
}
