"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
import { RequireRole } from "@/components/AppShell";
import { ErrorBox, Loading, RiskStatus } from "@/components/Status";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { RiskState } from "@/lib/types";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

interface Group {
  key: string;
  suppressed: boolean;
  reason?: string;
  fields?: number;
  states?: Record<string, number>;
  vegetation_current_share?: number;
  latest_vegetation_period_end?: string | null;
  synthetic_fields?: number;
}
interface Cell extends Group {
  cell: { lat: number; lon: number; dlat: number; dlon: number };
  rain_30d: { total_mm: number | null; percentile: number | null; reference_mean_mm: number | null; climatologically_dry: boolean } | null;
  weather_window_end: string | null;
}
interface Summary {
  generated_at: string;
  consenting_fields: number;
  min_group_size: number;
  districts: Group[];
  grid_cells: Cell[];
  notes: string[];
}

function StateCounts({ states }: { states: Record<string, number> | undefined }) {
  const { t } = useI18n();
  return (
    <div className="row">
      {Object.entries(states ?? {}).map(([s, n]) => (
        <span key={s} className="small">
          {s === "no_current_assessment" ? <span className="badge badge-muted">{t("regional.no_current")}</span> : <RiskStatus state={s as RiskState} />} {n}
        </span>
      ))}
    </div>
  );
}

function Regional() {
  const { t, fmtDate, fmtNum } = useI18n();
  const [crop, setCrop] = useState("");
  const [season, setSeason] = useState("");
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState<unknown>(null);
  useEffect(() => {
    const q = new URLSearchParams();
    if (crop) q.set("crop", crop);
    if (season) q.set("season", season);
    api<Summary>(`/api/v1/regional/summary?${q}`).then(setData).catch(setError);
  }, [crop, season]);

  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const shapes = data.grid_cells.map((c) => ({
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [c.cell.lon - c.cell.dlon / 2, c.cell.lat - c.cell.dlat / 2],
          [c.cell.lon + c.cell.dlon / 2, c.cell.lat - c.cell.dlat / 2],
          [c.cell.lon + c.cell.dlon / 2, c.cell.lat + c.cell.dlat / 2],
          [c.cell.lon - c.cell.dlon / 2, c.cell.lat + c.cell.dlat / 2],
          [c.cell.lon - c.cell.dlon / 2, c.cell.lat - c.cell.dlat / 2],
        ],
      ],
    } as GeoJSON.Polygon,
    label: t("regional.cell_tooltip", { n: c.fields, p: c.rain_30d?.percentile === null || c.rain_30d?.percentile === undefined ? "—" : fmtNum(c.rain_30d.percentile, 0), end: fmtDate(c.weather_window_end) }),
  }));
  return (
    <>
      <h1>{t("regional.title")}</h1>
      <div className="warn small">
        {data.notes.map((n) => (
          <p key={n} style={{ margin: "2px 0" }}>
            {n}
          </p>
        ))}
      </div>
      <div className="card row">
        <label className="small">
          {t("register_field.crop")}
          <input value={crop} onChange={(e) => setCrop(e.target.value)} placeholder={t("common.any")} />
        </label>
        <label className="small">
          {t("register_field.season")}
          <select value={season} onChange={(e) => setSeason(e.target.value)}>
            <option value="">{t("common.any")}</option>
            {["kharif", "rabi", "zaid", "annual"].map((s) => (
              <option key={s} value={s}>
                {t(`season.${s}`)}
              </option>
            ))}
          </select>
        </label>
        <span className="small muted">{t("regional.meta", { n: data.consenting_fields, k: data.min_group_size, date: fmtDate(data.generated_at) })}</span>
      </div>
      <section className="card">
        <h2>{t("regional.map_title")}</h2>
        <p className="small muted">{t("regional.map_note")}</p>
        <MapView shapes={shapes} ariaLabel={t("regional.map_title")} height={360} />
      </section>
      <section className="card table-wrap">
        <h2>{t("regional.districts")}</h2>
        <table>
          <thead>
            <tr>
              <th>{t("register_field.district")}</th>
              <th>{t("regional.fields")}</th>
              <th>{t("regional.states")}</th>
              <th>{t("regional.veg_current")}</th>
              <th>{t("regional.latest_composite")}</th>
            </tr>
          </thead>
          <tbody>
            {data.districts.map((d) => (
              <tr key={d.key}>
                <td>{d.key}</td>
                {d.suppressed ? (
                  <td colSpan={4} className="muted">
                    {t("regional.suppressed", { k: data.min_group_size })}
                  </td>
                ) : (
                  <>
                    <td>
                      {d.fields} {d.synthetic_fields ? <span className="kind kind-synthetic">{t("regional.synthetic_n", { n: d.synthetic_fields })}</span> : null}
                    </td>
                    <td>
                      <StateCounts states={d.states} />
                    </td>
                    <td>{fmtNum((d.vegetation_current_share ?? 0) * 100, 0)}%</td>
                    <td>{fmtDate(d.latest_vegetation_period_end)}</td>
                  </>
                )}
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
    <RequireRole roles={["regional_analyst", "researcher", "admin"]}>
      <Regional />
    </RequireRole>
  );
}
