"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { RequireRole } from "@/components/AppShell";
import { RainfallChart, VegetationChart } from "@/components/Charts";
import { EvidenceChecks, ExplanationList, GuidanceBlock } from "@/components/Evidence";
import { CachedBanner, CaseStatusBadge, DataKindTag, DataQualityWarning, ErrorBox, FreshnessBadge, Loading, RiskStatus, SourceTag, SyntheticBanner, UncertaintyNote } from "@/components/Status";
import { api, apiCached, type Cached } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Assessment, CaseOut, FieldOut, VegSeries, WeatherOut } from "@/lib/types";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

interface Job {
  id: string;
  source_id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  records_written: number;
  records_unchanged: number;
  records_rejected: number;
  warnings: string[];
  message: string | null;
}

function FieldDetail() {
  const { id } = useParams<{ id: string }>();
  const { t, fmtDate, fmtNum } = useI18n();
  const [field, setField] = useState<Cached<FieldOut> | null>(null);
  const [assessment, setAssessment] = useState<Cached<Assessment | null> | null>(null);
  const [veg, setVeg] = useState<Cached<VegSeries> | null>(null);
  const [wx, setWx] = useState<Cached<WeatherOut> | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [cases, setCases] = useState<CaseOut[]>([]);
  const [recs, setRecs] = useState<{ kind: string; body: string | null; created_at: string; data_kind: string }[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [years, setYears] = useState(2);

  const load = useCallback(async () => {
    try {
      const [f, a] = await Promise.all([apiCached<FieldOut>(`/api/v1/fields/${id}`), apiCached<Assessment | null>(`/api/v1/fields/${id}/assessments/latest`)]);
      setField(f);
      setAssessment(a);
      apiCached<VegSeries>(`/api/v1/fields/${id}/vegetation?years=${years}`).then(setVeg).catch(() => undefined);
      apiCached<WeatherOut>(`/api/v1/fields/${id}/weather?days=90`).then(setWx).catch(() => undefined);
      api<Job[]>(`/api/v1/fields/${id}/jobs`).then(setJobs).catch(() => undefined);
      api<CaseOut[]>(`/api/v1/fields/${id}/cases`).then(setCases).catch(() => undefined);
      api<typeof recs>(`/api/v1/fields/${id}/recommendations`).then(setRecs).catch(() => undefined);
    } catch (e) {
      setError(e);
    }
  }, [id, years]);

  useEffect(() => {
    void load();
  }, [load]);

  const running = jobs.some((j) => j.status === "running");
  useEffect(() => {
    if (!running) return;
    const h = setInterval(() => void load(), 15000);
    return () => clearInterval(h);
  }, [running, load]);

  if (error) return <ErrorBox error={error} />;
  if (!field || !assessment) return <Loading />;
  const f = field.data;
  const a = assessment.data;
  const season = f.seasons.filter((s) => s.active).slice(-1)[0];
  const r30 = (a?.weather?.rain ?? []).find((w: { days: number }) => w.days === 30);

  return (
    <>
      <SyntheticBanner show={f.is_synthetic || Boolean(a?.is_synthetic)} />
      <CachedBanner fromCache={assessment.fromCache} fetchedAt={assessment.fetchedAt} />
      <div className="spread">
        <div>
          <h1>{f.name}</h1>
          <p className="muted small">
            {f.district} · {season ? `${t(`crop.${season.crop}`)} · ${t(`season.${season.season}`)} ${season.season_year}` : t("field.no_season")} ·{" "}
            {f.area_ha ? t("unit.ha", { v: fmtNum(f.area_ha, 1) }) : t("field.point_only")}
            {season?.sowing_date ? ` · ${t("field.sown", { date: fmtDate(season.sowing_date) })}${season.sowing_date_uncertain ? ` (${t("field.approx")})` : ""}` : ""}
          </p>
        </div>
        {f.is_owner ? (
          <div className="row">
            <Link className="btn" href={`/farmer/fields/${id}/report`}>
              {t("field.report_problem")}
            </Link>
            <button type="button" className="secondary" disabled={running} onClick={() => api(`/api/v1/fields/${id}/refresh`, { method: "POST" }).then(load).catch(setError)}>
              {running ? t("field.updating") : t("field.refresh")}
            </button>
          </div>
        ) : null}
      </div>

      {running ? <div className="notice">{t("field.ingest_running")}</div> : null}

      <section className="card" aria-labelledby="assessment-h">
        <h2 id="assessment-h">{t("field.current_assessment")}</h2>
        {!a ? (
          <p>{running ? t("field.no_assessment_yet_running") : t("field.no_assessment_yet")}</p>
        ) : (
          <>
            <div className="spread">
              <RiskStatus state={a.state} large />
              <span className="small muted">
                {t("field.assessed_at", { date: fmtDate(a.assessed_at) })} · <DataKindTag kind="estimated" />
              </span>
            </div>
            {a.is_expired ? <DataQualityWarning>{t("field.assessment_expired", { date: fmtDate(a.expires_at) })}</DataQualityWarning> : null}
            <p className="small">{t(`risk_help.${a.state}`)}</p>
            <h3>{t("field.next_step")}</h3>
            <GuidanceBlock a={a} />
            <h3>{t("field.why")}</h3>
            <ExplanationList items={a.explanations} />
            <UncertaintyNote a={a} />
            <EvidenceChecks a={a} />
          </>
        )}
      </section>

      <section className="card" aria-labelledby="fresh-h">
        <h2 id="fresh-h">{t("field.data_status")}</h2>
        <div className="fresh-row">
          <FreshnessBadge label={t("source.modis_mod13q1")} entry={a?.freshness.vegetation} />
          <FreshnessBadge label={t("source.nasa_power_daily")} entry={a?.freshness.weather} />
          <FreshnessBadge label={t("source.smap_l4")} entry={a?.freshness.soil_moisture ?? { status: "unavailable" }} />
        </div>
        <p className="small muted">{t("field.latency_note")}</p>
      </section>

      <section className="card" aria-labelledby="veg-h">
        <div className="spread">
          <h2 id="veg-h">{t("field.vegetation")}</h2>
          <label className="small">
            <span className="sr-only">{t("field.years")}</span>
            <select value={years} onChange={(e) => setYears(Number(e.target.value))}>
              {[1, 2, 3, 5].map((y) => (
                <option key={y} value={y}>
                  {t("field.last_years", { n: y })}
                </option>
              ))}
            </select>
          </label>
        </div>
        {veg ? (
          <>
            <CachedBanner fromCache={veg.fromCache} fetchedAt={veg.fetchedAt} />
            <VegetationChart points={veg.data.points} variable={veg.data.variable} />
            <p className="small muted">
              <DataKindTag kind="observed" /> <SourceTag sourceId={veg.data.source_id} /> · {veg.data.reference_description}
            </p>
            <p className="small muted">{t("field.pixel_note")}</p>
          </>
        ) : (
          <Loading />
        )}
      </section>

      <section className="card" aria-labelledby="wx-h">
        <h2 id="wx-h">{t("field.weather")}</h2>
        {r30 ? (
          <dl className="kv">
            <dt>{t("weather.rain30")}</dt>
            <dd>
              {r30.total_mm === null ? t("chart.missing") : t("unit.mm", { v: fmtNum(r30.total_mm, 0) })}
              {r30.percentile !== null && !r30.climatologically_dry ? ` · ${t("weather.percentile", { p: fmtNum(r30.percentile, 0) })}` : ""}
              {r30.climatologically_dry ? ` · ${t("weather.dry_season")}` : ""}
            </dd>
            <dt>{t("weather.usual30")}</dt>
            <dd>{r30.reference_mean_mm === null ? "—" : t("unit.mm", { v: fmtNum(r30.reference_mean_mm, 0) })}</dd>
            <dt>{t("weather.dry_spell")}</dt>
            <dd>{a?.weather?.current_dry_spell_days ?? "—"} {a?.weather?.dry_spell_truncated ? t("weather.at_least") : ""}</dd>
            <dt>{t("weather.heat_days", { c: a?.weather?.heat_threshold_c ?? 40, d: a?.weather?.heat_window_days ?? 14 })}</dt>
            <dd>{a?.weather?.heat_days ?? "—"}</dd>
            <dt>{t("weather.window_end")}</dt>
            <dd>{fmtDate(a?.weather?.window_end)}</dd>
          </dl>
        ) : null}
        {wx ? (
          <>
            <RainfallChart wx={wx.data} />
            <p className="small muted">
              <DataKindTag kind="observed" /> <SourceTag sourceId="nasa_power_daily" /> · {t("weather.grid_note")}
            </p>
          </>
        ) : (
          <Loading />
        )}
      </section>

      <section className="card" aria-labelledby="map-h">
        <h2 id="map-h">{t("field.map")}</h2>
        <MapView shapes={[{ geometry: f.geometry_geojson, label: f.name }]} ariaLabel={t("map.field_aria")} />
        <p className="small muted">{t("field.boundary_version", { v: f.boundary_version })}</p>
      </section>

      <section className="card" aria-labelledby="exp-h">
        <h2 id="exp-h">{t("field.expert")}</h2>
        {cases.length === 0 ? <p className="small muted">{t("field.no_cases")}</p> : null}
        {cases.map((c) => (
          <p key={c.id}>
            <CaseStatusBadge status={c.status} /> <span className="small muted">{t("field.case_opened", { date: fmtDate(c.created_at) })}</span>
          </p>
        ))}
        {recs.map((r, i) => (
          <div key={i} className="guidance-item">
            <p>{r.body ?? t(`case_event.${r.kind}`)}</p>
            <p className="small muted">
              <DataKindTag kind={r.data_kind} /> {t(`case_event.${r.kind}`)} · {fmtDate(r.created_at)}
            </p>
          </div>
        ))}
      </section>

      <details className="card">
        <summary>{t("field.processing_log")}</summary>
        <table>
          <thead>
            <tr>
              <th>{t("jobs.source")}</th>
              <th>{t("jobs.status")}</th>
              <th>{t("jobs.when")}</th>
              <th>{t("jobs.records")}</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id}>
                <td>{t(`source.${j.source_id}`)}</td>
                <td>
                  {t(`job.${j.status}`)}
                  {j.message ? <div className="small muted">{j.message}</div> : null}
                </td>
                <td>{fmtDate(j.started_at)}</td>
                <td>{t("jobs.counts", { w: j.records_written, u: j.records_unchanged, r: j.records_rejected })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["farmer", "agronomist", "fpo_manager", "admin"]}>
      <FieldDetail />
    </RequireRole>
  );
}
