"use client";

import { DataKindTag, SourceTag } from "@/components/Status";
import { useI18n } from "@/lib/i18n";
import type { Assessment, Explanation } from "@/lib/types";

/** Renders explanation records produced by the risk engine from its actual inputs. */
export function ExplanationList({ items }: { items: Explanation[] }) {
  const { t, fmtDate } = useI18n();
  const fmt = (p: Explanation["params"]) => {
    const out: Record<string, unknown> = { ...p };
    for (const k of ["period_start", "period_end", "window_end"]) if (typeof p[k] === "string") out[k] = fmtDate(p[k] as string);
    return out;
  };
  return (
    <ul className="evidence">
      {items.map((e, i) => (
        <li key={`${e.key}-${i}`}>
          <span>{t(e.key, fmt(e.params))}</span>
          <span className="evidence-tags">
            <DataKindTag kind={e.kind} />
            <SourceTag sourceId={e.source} />
          </span>
        </li>
      ))}
    </ul>
  );
}

export function EvidenceChecks({ a }: { a: Assessment }) {
  const { t } = useI18n();
  return (
    <details>
      <summary>{t("evidence.checks_title", { status: t(`sufficiency.${a.sufficiency}`) })}</summary>
      <ul className="checks">
        {a.sufficiency_checks.map((c) => (
          <li key={c.id} className={c.passed ? "pass" : c.severity === "info" ? "info" : "fail"}>
            <span aria-hidden="true">{c.passed ? "✓" : c.severity === "info" ? "i" : "✗"}</span> {t(`check.${c.id}`)} — <span className="muted">{t(`check_detail.${c.detail}`, c.params)}</span>
          </li>
        ))}
      </ul>
      <p className="small muted">
        {t("evidence.model_line", { model: a.model_name, version: a.model_version, config: a.config_version })} {a.model_validated ? t("evidence.validated") : t("evidence.not_validated")}
      </p>
    </details>
  );
}

export function GuidanceBlock({ a }: { a: Assessment }) {
  const { t } = useI18n();
  if (!a.guidance.length) return <p className="muted">{t("guidance.none")}</p>;
  return (
    <div className="guidance">
      {a.guidance.map((g) => (
        <div key={g.id} className="guidance-item">
          <p>{g.body}</p>
          {g.translation_pending && g.unreviewed_translation ? (
            <details>
              <summary>{t("guidance.unreviewed_translation")}</summary>
              <p>{g.unreviewed_translation}</p>
            </details>
          ) : null}
          <p className="small muted">
            {t("guidance.source", { org: g.source_org ?? "—" })} {g.limitations ? `· ${g.limitations}` : ""}
          </p>
        </div>
      ))}
    </div>
  );
}
