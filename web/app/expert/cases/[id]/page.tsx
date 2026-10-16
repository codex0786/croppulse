"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { RequireRole } from "@/components/AppShell";
import { EvidenceChecks, ExplanationList } from "@/components/Evidence";
import { CaseStatusBadge, DataKindTag, ErrorBox, FreshnessBadge, Loading, RiskStatus, SyntheticBanner, UncertaintyNote } from "@/components/Status";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import type { CaseDetail } from "@/lib/types";

function CaseView() {
  const { id } = useParams<{ id: string }>();
  const { t, fmtDate } = useI18n();
  const { user } = useSession();
  const [c, setC] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [ev, setEv] = useState({ kind: "comment", body: "", scheduled_for: "", source_ref: "" });
  const [vf, setVf] = useState({ finding: "stress_confirmed", suspected_cause: "", observed_on: new Date().toISOString().slice(0, 10), method: "field_inspection", notes: "" });

  const load = useCallback(() => api<CaseDetail>(`/api/v1/cases/${id}`).then(setC).catch(setError), [id]);
  useEffect(() => {
    void load();
  }, [load]);
  const act = (p: Promise<unknown>) => p.then(load).catch(setError);

  if (error && !c) return <ErrorBox error={error} />;
  if (!c) return <Loading />;
  const a = c.assessment;
  const closed = c.status === "closed";
  return (
    <>
      <SyntheticBanner show={Boolean(a?.is_synthetic)} />
      <div className="spread">
        <h1>
          {c.field_name} <span className="small muted">({c.district})</span>
        </h1>
        <CaseStatusBadge status={c.status} />
      </div>
      <p className="small muted">
        {t(`origin.${c.origin}`)} · {t("expert.opened", { date: fmtDate(c.created_at) })} · {t(`priority.${c.priority}`)} ·{" "}
        <Link href={`/farmer/fields/${c.field_id}`}>{t("expert.open_field")}</Link>
      </p>
      <ErrorBox error={error} />
      <div className="row">
        {!c.assigned_to ? <button onClick={() => act(api(`/api/v1/cases/${id}/assign`, { method: "POST", body: {} }))}>{t("expert.assign_me")}</button> : <span className="small">{t("expert.assigned")}</span>}
        {closed ? (
          <button className="secondary" onClick={() => act(api(`/api/v1/cases/${id}/reopen`, { method: "POST" }))}>
            {t("expert.reopen")}
          </button>
        ) : (
          <button className="secondary" onClick={() => act(api(`/api/v1/cases/${id}/close`, { method: "POST" }))}>
            {t("expert.close")}
          </button>
        )}
      </div>

      <div className="grid2">
        <section className="card">
          <h2>{t("expert.machine_evidence")}</h2>
          <p className="small muted">{t("expert.machine_note")}</p>
          {a ? (
            <>
              <RiskStatus state={a.state} /> <DataKindTag kind="estimated" />
              <div className="fresh-row" style={{ marginTop: 8 }}>
                <FreshnessBadge label={t("source.modis_mod13q1")} entry={a.freshness.vegetation} />
                <FreshnessBadge label={t("source.nasa_power_daily")} entry={a.freshness.weather} />
              </div>
              <ExplanationList items={a.explanations} />
              <UncertaintyNote a={a} />
              <EvidenceChecks a={a} />
            </>
          ) : (
            <p>{t("field.no_assessment_yet")}</p>
          )}
        </section>
        <section className="card">
          <h2>{t("expert.farmer_report")}</h2>
          {c.report ? (
            <>
              <p>
                <DataKindTag kind="farmer_reported" /> {c.report.symptoms.map((s) => t(`symptom.${s}`)).join(", ")}
              </p>
              <dl className="kv small">
                <dt>{t("report.observed_on")}</dt>
                <dd>{fmtDate(c.report.observed_on)}</dd>
                <dt>{t("report.fraction")}</dt>
                <dd>{t(`fraction.${c.report.affected_fraction ?? "unknown"}`)}</dd>
                <dt>{t("report.photos")}</dt>
                <dd>{c.report.photos.length}</dd>
              </dl>
              {c.report.description ? <p>{c.report.description}</p> : null}
            </>
          ) : (
            <p className="muted">{t("expert.no_report")}</p>
          )}
          {c.outcome ? (
            <div className="note">
              <DataKindTag kind="expert_verified" /> {t(`finding.${c.outcome.finding}`)} · {fmtDate(c.outcome.observed_on)} · {t(`method.${c.outcome.method}`)}
              {c.outcome.notes ? <p>{c.outcome.notes}</p> : null}
            </div>
          ) : null}
        </section>
      </div>

      <section className="card">
        <h2>{t("expert.history")}</h2>
        <ul className="list">
          {c.events.map((e) => (
            <li key={e.id}>
              <strong>{t(`case_event.${e.kind}`)}</strong> <span className={`kind ${e.authored_by === "system" ? "" : "kind-expert_authored"}`}>{t(`authored.${e.authored_by}`)}</span>{" "}
              <span className="small muted">{fmtDate(e.created_at)}</span>
              {e.body ? <p>{e.body}</p> : null}
              {e.data?.scheduled_for ? <p className="small">{t("expert.scheduled_for", { date: fmtDate(e.data.scheduled_for) })}</p> : null}
              {e.data?.source_ref ? <p className="small">{t("expert.source_ref", { ref: e.data.source_ref })}</p> : null}
            </li>
          ))}
        </ul>
      </section>

      {!closed ? (
        <div className="grid2">
          <form
            className="card"
            onSubmit={(e) => {
              e.preventDefault();
              act(api(`/api/v1/cases/${id}/events`, { method: "POST", body: { kind: ev.kind, body: ev.body, scheduled_for: ev.scheduled_for || null, source_ref: ev.source_ref || null } })).then(() =>
                setEv({ ...ev, body: "" }),
              );
            }}
          >
            <h2>{t("expert.add_entry")}</h2>
            <label htmlFor="kind">{t("expert.entry_kind")}</label>
            <select id="kind" value={ev.kind} onChange={(e) => setEv({ ...ev, kind: e.target.value })}>
              {["comment", "info_request", "inspection_scheduled", "recommendation"].map((k) => (
                <option key={k} value={k}>
                  {t(`case_event.${k}`)}
                </option>
              ))}
            </select>
            {ev.kind === "inspection_scheduled" ? (
              <>
                <label htmlFor="sf">{t("expert.date")}</label>
                <input id="sf" type="date" required value={ev.scheduled_for} onChange={(e) => setEv({ ...ev, scheduled_for: e.target.value })} />
              </>
            ) : null}
            {ev.kind === "recommendation" ? (
              <>
                <label htmlFor="sr">{t("expert.source_ref_label")}</label>
                <input id="sr" value={ev.source_ref} onChange={(e) => setEv({ ...ev, source_ref: e.target.value })} />
                <p className="small muted">{t("expert.recommendation_note")}</p>
              </>
            ) : null}
            <label htmlFor="body">{t("expert.text")}</label>
            <textarea id="body" required rows={4} value={ev.body} onChange={(e) => setEv({ ...ev, body: e.target.value })} />
            <button type="submit">{t("common.save")}</button>
          </form>
          {!c.outcome && user?.role === "agronomist" ? (
            <form
              className="card"
              onSubmit={(e) => {
                e.preventDefault();
                if (!window.confirm(t("expert.verify_confirm"))) return;
                act(api(`/api/v1/cases/${id}/verify`, { method: "POST", body: { ...vf, suspected_cause: vf.suspected_cause || null, notes: vf.notes || null } }));
              }}
            >
              <h2>{t("expert.verify_title")}</h2>
              <p className="small muted">{t("expert.verify_note")}</p>
              <label htmlFor="finding">{t("expert.finding")}</label>
              <select id="finding" value={vf.finding} onChange={(e) => setVf({ ...vf, finding: e.target.value })}>
                {["stress_confirmed", "no_stress_found", "false_alarm", "data_problem", "inconclusive"].map((k) => (
                  <option key={k} value={k}>
                    {t(`finding.${k}`)}
                  </option>
                ))}
              </select>
              <label htmlFor="cause">{t("expert.suspected_cause")}</label>
              <input id="cause" maxLength={80} value={vf.suspected_cause} onChange={(e) => setVf({ ...vf, suspected_cause: e.target.value })} />
              <label htmlFor="vobs">{t("report.observed_on")}</label>
              <input id="vobs" type="date" required value={vf.observed_on} max={new Date().toISOString().slice(0, 10)} onChange={(e) => setVf({ ...vf, observed_on: e.target.value })} />
              <label htmlFor="method">{t("expert.method")}</label>
              <select id="method" value={vf.method} onChange={(e) => setVf({ ...vf, method: e.target.value })}>
                {["field_inspection", "remote_review", "phone_call"].map((k) => (
                  <option key={k} value={k}>
                    {t(`method.${k}`)}
                  </option>
                ))}
              </select>
              <label htmlFor="notes">{t("expert.notes")}</label>
              <textarea id="notes" rows={3} value={vf.notes} onChange={(e) => setVf({ ...vf, notes: e.target.value })} />
              <button type="submit">{t("expert.verify_submit")}</button>
            </form>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["agronomist", "admin"]}>
      <CaseView />
    </RequireRole>
  );
}
