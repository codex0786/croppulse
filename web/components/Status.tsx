"use client";

// Reusable status components: risk state, freshness, data kind, source, observation
// period, uncertainty, data-quality warning, synthetic banner, case status.
// Each conveys meaning with text + shape, never colour alone.

import { useI18n } from "@/lib/i18n";
import type { Assessment, DataKind, FreshnessEntry, RiskState } from "@/lib/types";

const RISK_ICON: Record<RiskState, string> = {
  insufficient_evidence: "?",
  normal_for_reference_period: "✓",
  watch: "!",
  elevated_risk: "▲",
  expert_review_recommended: "▲",
  verified_stress: "■",
  resolved: "✓",
};

export function RiskStatus({ state, large = false }: { state: RiskState | null; large?: boolean }) {
  const { t } = useI18n();
  if (!state) return <span className="badge badge-muted">{t("risk.not_assessed")}</span>;
  return (
    <span className={`badge risk-${state} ${large ? "badge-large" : ""}`} role="status">
      <span aria-hidden="true" className="badge-icon">
        {RISK_ICON[state]}
      </span>
      {t(`risk.${state}`)}
    </span>
  );
}

export function FreshnessBadge({ label, entry }: { label: string; entry: FreshnessEntry | undefined }) {
  const { t, fmtDate } = useI18n();
  const status = entry?.status ?? "unavailable";
  const end = entry?.period_end ?? entry?.window_end ?? null;
  return (
    <div className={`fresh fresh-${status}`}>
      <strong>{label}</strong>
      <span className="fresh-status">
        <span aria-hidden="true">{status === "current" ? "●" : status === "stale" ? "◐" : "○"}</span> {t(`freshness.${status}`)}
      </span>
      {end ? <span className="muted small">{t("freshness.data_until", { date: fmtDate(end), days: entry?.age_days ?? "—" })}</span> : null}
    </div>
  );
}

export function DataKindTag({ kind }: { kind: DataKind | string }) {
  const { t } = useI18n();
  return <span className={`kind kind-${kind}`}>{t(`kind.${kind}`)}</span>;
}

export function SourceTag({ sourceId }: { sourceId: string | undefined }) {
  const { t } = useI18n();
  if (!sourceId) return null;
  return <span className="source">{t(`source.${sourceId}`)}</span>;
}

export function ObservationPeriod({ start, end }: { start: string | null | undefined; end: string | null | undefined }) {
  const { t, fmtDate } = useI18n();
  if (!start && !end) return null;
  return <span className="small">{t("period.range", { start: fmtDate(start), end: fmtDate(end) })}</span>;
}

export function UncertaintyNote({ a }: { a: Assessment }) {
  const { t, fmtNum } = useI18n();
  const u = a.uncertainty ?? {};
  return (
    <div className="note">
      <p>
        <strong>{t("uncertainty.title")}</strong> {t(u.statement_key ?? "uncertainty_screening_unvalidated")}
      </p>
      <ul className="small">
        <li>{t("uncertainty.reference_years", { n: u.reference_n ?? 0 })}</li>
        {u.robust_z_interval_5_95 ? <li>{t("uncertainty.z_interval", { lo: fmtNum(u.robust_z_interval_5_95[0], 1), hi: fmtNum(u.robust_z_interval_5_95[1], 1) })}</li> : null}
        {u.valid_pixel_fraction !== null && u.valid_pixel_fraction !== undefined ? <li>{t("uncertainty.valid_pixels", { pct: fmtNum(u.valid_pixel_fraction * 100, 0) })}</li> : null}
        {u.pixel_rule === "pixel_containing_centroid" ? <li>{t("uncertainty.single_pixel")}</li> : null}
        <li>{t("uncertainty.no_probability")}</li>
      </ul>
    </div>
  );
}

export function DataQualityWarning({ children }: { children: React.ReactNode }) {
  return (
    <div className="warn" role="note">
      <span aria-hidden="true">⚠ </span>
      {children}
    </div>
  );
}

export function SyntheticBanner({ show }: { show: boolean }) {
  const { t } = useI18n();
  if (!show) return null;
  return (
    <div className="synthetic" role="alert">
      <strong>{t("synthetic.title")}</strong> {t("synthetic.body")}
    </div>
  );
}

export function CachedBanner({ fromCache, fetchedAt }: { fromCache: boolean; fetchedAt: string }) {
  const { t, fmtDate } = useI18n();
  if (!fromCache) return null;
  return (
    <div className="warn" role="status">
      {t("offline.cached", { time: `${fmtDate(fetchedAt)} ${new Date(fetchedAt).toLocaleTimeString()}` })}
    </div>
  );
}

export function CaseStatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  return <span className={`badge case-${status}`}>{t(`case.${status}`)}</span>;
}

export function Loading() {
  const { t } = useI18n();
  return (
    <p className="muted" aria-live="polite">
      {t("common.loading")}
    </p>
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  const { t } = useI18n();
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="error" role="alert">
      {t("common.error")}: {msg}
    </div>
  );
}
