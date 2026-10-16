"use client";

import Link from "next/link";
import { ExplanationList } from "@/components/Evidence";
import { RiskStatus } from "@/components/Status";
import { useI18n } from "@/lib/i18n";
import type { Alert } from "@/lib/types";

export function AlertCard({ a, onAck }: { a: Alert; onAck?: () => void }) {
  const { t, fmtDate } = useI18n();
  return (
    <article className="card" aria-labelledby={`al-${a.id}`}>
      <div className="spread">
        <h2 id={`al-${a.id}`}>{t(a.title_key)}</h2>
        <RiskStatus state={a.severity} />
      </div>
      <p>{t(a.message_key)}</p>
      {a.requires_expert ? <p className="note small">{t("alert.expert_required")}</p> : null}
      <details>
        <summary>{t("alert.why")}</summary>
        <ExplanationList items={a.explanation} />
        <p className="small muted">
          {t("alert.meta", { created: fmtDate(a.created_at), expires: fmtDate(a.expires_at), rule: `${a.rule_id}@${a.rule_version}`, model: a.model_version })}
        </p>
      </details>
      <div className="row">
        <Link href={`/farmer/fields/${a.field_id}`}>{t("alert.open_field")}</Link>
        {onAck && !a.acknowledged_at ? (
          <button type="button" className="secondary" onClick={onAck}>
            {t("alert.acknowledge")}
          </button>
        ) : a.acknowledged_at ? (
          <span className="small muted">{t("alert.acknowledged", { date: fmtDate(a.acknowledged_at) })}</span>
        ) : null}
      </div>
    </article>
  );
}
