"use client";

// Hand-rolled SVG charts (no chart library: small bundle for low-bandwidth use).
// - Vegetation: observed NDVI line + historical 10th–90th percentile band + median.
//   Composites with no usable observation are drawn as hollow ticks on the axis
//   labelled "no usable observation" — never as a value of zero.
// - Rainfall: daily bars, with missing days marked separately from 0 mm.
// Both have a hover tooltip and a data-table view.

import { useMemo, useState } from "react";
import { useI18n } from "@/lib/i18n";
import type { VegPoint, WeatherOut } from "@/lib/types";

const W = 640;
const H = 240;
const M = { top: 12, right: 12, bottom: 32, left: 44 };

function scaleTime(dates: number[]) {
  const min = Math.min(...dates);
  const max = Math.max(...dates);
  const span = Math.max(1, max - min);
  return (t: number) => M.left + ((t - min) / span) * (W - M.left - M.right);
}

function ticks(min: number, max: number, n = 5): number[] {
  const step = (max - min) / (n - 1);
  return Array.from({ length: n }, (_, i) => min + i * step);
}

export function VegetationChart({ points, variable }: { points: VegPoint[]; variable: string }) {
  const { t, fmtDate, fmtNum } = useI18n();
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const mids = points.map((p) => (Date.parse(p.period_start) + Date.parse(p.period_end)) / 2);
  const x = useMemo(() => scaleTime(mids), [mids]);
  if (!points.length) return <p className="muted">{t("chart.no_vegetation")}</p>;
  const vals = points.flatMap((p) => [p.value, p.reference_p10, p.reference_p90]).filter((v): v is number => v !== null);
  const yMin = Math.max(-0.2, Math.floor((Math.min(...vals, 0.1) - 0.05) * 10) / 10);
  const yMax = Math.min(1, Math.ceil((Math.max(...vals, 0.5) + 0.05) * 10) / 10);
  const y = (v: number) => M.top + (1 - (v - yMin) / (yMax - yMin)) * (H - M.top - M.bottom);
  const band = points
    .map((p, i) => (p.reference_p10 !== null && p.reference_p90 !== null ? { i, lo: p.reference_p10, hi: p.reference_p90 } : null))
    .filter((b): b is { i: number; lo: number; hi: number } => b !== null);
  const bandPath = band.length
    ? `M${band.map((b) => `${x(mids[b.i])},${y(b.hi)}`).join("L")}L${[...band].reverse().map((b) => `${x(mids[b.i])},${y(b.lo)}`).join("L")}Z`
    : "";
  const segs: string[] = [];
  let cur: string[] = [];
  points.forEach((p, i) => {
    if (p.value !== null && p.accepted) cur.push(`${x(mids[i])},${y(p.value)}`);
    else if (cur.length) {
      segs.push(cur.join("L"));
      cur = [];
    }
  });
  if (cur.length) segs.push(cur.join("L"));
  const median = points.map((p, i) => (p.reference_median !== null ? `${x(mids[i])},${y(p.reference_median)}` : null)).filter(Boolean);
  const years = Array.from(new Set(points.map((p) => p.period_start.slice(0, 4))));
  const h = hover !== null ? points[hover] : null;

  return (
    <figure className="chart viz-root">
      <figcaption className="chart-caption">
        <strong>{t("chart.veg_title", { variable })}</strong>
        <span className="chart-key">
          <span className="key-line" /> {t("chart.key_observed")}
          <span className="key-band" /> {t("chart.key_band")}
          <span className="key-median" /> {t("chart.key_median")}
          <span className="key-missing">◦</span> {t("chart.key_missing")}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("chart.veg_aria", { n: points.length })} onMouseLeave={() => setHover(null)}>
        {ticks(yMin, yMax).map((v) => (
          <g key={v}>
            <line x1={M.left} x2={W - M.right} y1={y(v)} y2={y(v)} className="grid" />
            <text x={M.left - 6} y={y(v) + 4} className="axis" textAnchor="end">
              {fmtNum(v, 1)}
            </text>
          </g>
        ))}
        {years.map((yr) => {
          const tx = x(Date.parse(`${yr}-01-01`));
          return tx >= M.left ? (
            <text key={yr} x={tx} y={H - 8} className="axis" textAnchor="middle">
              {yr}
            </text>
          ) : null;
        })}
        {bandPath ? <path d={bandPath} className="ref-band" /> : null}
        {median.length > 1 ? <path d={`M${median.join("L")}`} className="ref-median" /> : null}
        {segs.map((s, i) => (
          <path key={i} d={`M${s}`} className="series-line" />
        ))}
        {points.map((p, i) =>
          p.value !== null && p.accepted ? (
            <circle key={i} cx={x(mids[i])} cy={y(p.value)} r={hover === i ? 5 : 3} className="series-dot" />
          ) : (
            <text key={i} x={x(mids[i])} y={H - M.bottom + 2} className="missing-tick" textAnchor="middle">
              ◦
            </text>
          ),
        )}
        {points.map((_, i) => (
          <rect key={`hit-${i}`} x={x(mids[i]) - 8} y={M.top} width={16} height={H - M.top - M.bottom} fill="transparent" onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={-1} />
        ))}
        {h && hover !== null ? <line x1={x(mids[hover])} x2={x(mids[hover])} y1={M.top} y2={H - M.bottom} className="crosshair" /> : null}
      </svg>
      <div className="tooltip-line small" aria-live="polite">
        {h
          ? t(h.value !== null && h.accepted ? "chart.tooltip_veg" : "chart.tooltip_veg_missing", {
              start: fmtDate(h.period_start),
              end: fmtDate(h.period_end),
              value: fmtNum(h.value, 3),
              median: fmtNum(h.reference_median, 3),
              n: h.reference_n,
              reason: h.rejection_reason ? t(`reject.${h.rejection_reason}`) : "",
            })
          : t("chart.hover_hint")}
      </div>
      <button type="button" className="link" onClick={() => setTable(!table)}>
        {table ? t("chart.hide_table") : t("chart.show_table")}
      </button>
      {table ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("chart.col_period")}</th>
                <th>{variable}</th>
                <th>{t("chart.col_quality")}</th>
                <th>{t("chart.col_median")}</th>
                <th>{t("chart.col_n")}</th>
              </tr>
            </thead>
            <tbody>
              {[...points].reverse().map((p) => (
                <tr key={p.period_start}>
                  <td>{t("period.range", { start: fmtDate(p.period_start), end: fmtDate(p.period_end) })}</td>
                  <td>{p.value !== null && p.accepted ? fmtNum(p.value, 3) : t("chart.no_usable")}</td>
                  <td>{p.accepted ? fmtNum((p.valid_fraction ?? 0) * 100, 0) + "%" : t(`reject.${p.rejection_reason ?? "unknown"}`)}</td>
                  <td>{fmtNum(p.reference_median, 3)}</td>
                  <td>{p.reference_n}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </figure>
  );
}

export function RainfallChart({ wx }: { wx: WeatherOut }) {
  const { t, fmtDate, fmtNum } = useI18n();
  const [hover, setHover] = useState<number | null>(null);
  const [table, setTable] = useState(false);
  const d = wx.daily;
  if (!d.length) return <p className="muted">{t("chart.no_weather")}</p>;
  const maxR = Math.max(5, ...d.map((x) => x.precipitation_mm ?? 0));
  const bw = (W - M.left - M.right) / d.length;
  const y = (v: number) => M.top + (1 - v / maxR) * (H - M.top - M.bottom);
  const h = hover !== null ? d[hover] : null;
  return (
    <figure className="chart viz-root">
      <figcaption className="chart-caption">
        <strong>{t("chart.rain_title", { unit: wx.units.PRECTOTCORR ?? "mm/day" })}</strong>
        <span className="chart-key">
          <span className="key-bar" /> {t("chart.key_rain")} <span className="key-missing">×</span> {t("chart.key_missing_day")}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t("chart.rain_aria", { n: d.length })} onMouseLeave={() => setHover(null)}>
        {ticks(0, maxR).map((v) => (
          <g key={v}>
            <line x1={M.left} x2={W - M.right} y1={y(v)} y2={y(v)} className="grid" />
            <text x={M.left - 6} y={y(v) + 4} className="axis" textAnchor="end">
              {fmtNum(v, 0)}
            </text>
          </g>
        ))}
        {d.map((r, i) =>
          r.precipitation_mm === null ? (
            <text key={i} x={M.left + i * bw + bw / 2} y={H - M.bottom + 2} className="missing-tick" textAnchor="middle">
              ×
            </text>
          ) : r.precipitation_mm > 0 ? (
            <rect key={i} x={M.left + i * bw + 1} y={y(r.precipitation_mm)} width={Math.max(1, bw - 2)} height={H - M.bottom - y(r.precipitation_mm)} rx={Math.min(2, bw / 4)} className={hover === i ? "bar bar-hover" : "bar"} />
          ) : null,
        )}
        {[0, Math.floor(d.length / 2), d.length - 1].map((i) => (
          <text key={i} x={M.left + i * bw + bw / 2} y={H - 8} className="axis" textAnchor="middle">
            {fmtDate(d[i].date)}
          </text>
        ))}
        {d.map((_, i) => (
          <rect key={`hit-${i}`} x={M.left + i * bw} y={M.top} width={bw} height={H - M.top - M.bottom} fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
      </svg>
      <div className="tooltip-line small" aria-live="polite">
        {h ? (h.precipitation_mm === null ? t("chart.tooltip_rain_missing", { date: fmtDate(h.date) }) : t("chart.tooltip_rain", { date: fmtDate(h.date), mm: fmtNum(h.precipitation_mm, 1), tmax: fmtNum(h.tmax_c, 1) })) : t("chart.hover_hint")}
      </div>
      <button type="button" className="link" onClick={() => setTable(!table)}>
        {table ? t("chart.hide_table") : t("chart.show_table")}
      </button>
      {table ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t("chart.col_date")}</th>
                <th>{t("chart.col_rain")}</th>
                <th>{t("chart.col_tmax")}</th>
                <th>{t("chart.col_tmin")}</th>
              </tr>
            </thead>
            <tbody>
              {[...d].reverse().map((r) => (
                <tr key={r.date}>
                  <td>{fmtDate(r.date)}</td>
                  <td>{r.precipitation_mm === null ? t("chart.missing") : fmtNum(r.precipitation_mm, 1)}</td>
                  <td>{fmtNum(r.tmax_c, 1)}</td>
                  <td>{fmtNum(r.tmin_c, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </figure>
  );
}
