"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { RequireRole } from "@/components/AppShell";
import { ErrorBox } from "@/components/Status";
import { api, ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { enqueue, newClientRef } from "@/lib/offlineQueue";
import type { Report } from "@/lib/types";

const SYMPTOMS = ["wilting", "yellowing", "unusual_growth", "waterlogging", "pest_or_disease", "irrigation_problem", "other"];

function ReportForm() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useI18n();
  const [symptoms, setSymptoms] = useState<string[]>([]);
  const [observedOn, setObservedOn] = useState(new Date().toISOString().slice(0, 10));
  const [fraction, setFraction] = useState("unknown");
  const [description, setDescription] = useState("");
  const [started, setStarted] = useState("unknown");
  const [irrigated, setIrrigated] = useState("unknown");
  const [expert, setExpert] = useState(true);
  const [photos, setPhotos] = useState<FileList | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<"sent" | "queued" | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!symptoms.length) {
      setError(new Error(t("report.choose_symptom")));
      return;
    }
    setBusy(true);
    setError(null);
    const body = {
      symptoms,
      observed_on: observedOn,
      affected_fraction: fraction,
      description: description || null,
      answers: { when_started: started, irrigated_recently: irrigated },
      request_expert: expert,
      client_ref: newClientRef(),
    };
    try {
      const r = await api<Report>(`/api/v1/fields/${id}/reports`, { method: "POST", body });
      if (photos) {
        for (const file of Array.from(photos).slice(0, 5)) {
          const fd = new FormData();
          fd.append("file", file);
          await api(`/api/v1/reports/${r.id}/photos`, { method: "POST", form: fd });
        }
      }
      setDone("sent");
    } catch (err) {
      if (!(err instanceof ApiError)) {
        enqueue({ fieldId: id, body, queuedAt: new Date().toISOString() });
        setDone("queued");
      } else setError(err);
    } finally {
      setBusy(false);
    }
  };

  if (done)
    return (
      <div className="card">
        <h1>{done === "sent" ? t("report.sent_title") : t("report.queued_title")}</h1>
        <p>{done === "sent" ? (expert ? t("report.sent_expert") : t("report.sent")) : t("report.queued")}</p>
        <p className="small">{t("symptom_not_diagnosis")}</p>
        <button type="button" onClick={() => router.push(`/farmer/fields/${id}`)}>
          {t("report.back_to_field")}
        </button>
      </div>
    );

  return (
    <form className="card" onSubmit={submit}>
      <h1>{t("report.title")}</h1>
      <p className="small">{t("symptom_not_diagnosis")}</p>
      <fieldset>
        <legend>{t("report.what")}</legend>
        {SYMPTOMS.map((s) => (
          <label key={s} className="check">
            <input type="checkbox" checked={symptoms.includes(s)} onChange={(e) => setSymptoms(e.target.checked ? [...symptoms, s] : symptoms.filter((x) => x !== s))} />
            {t(`symptom.${s}`)}
          </label>
        ))}
      </fieldset>
      <label htmlFor="obs">{t("report.observed_on")}</label>
      <input id="obs" type="date" required max={new Date().toISOString().slice(0, 10)} value={observedOn} onChange={(e) => setObservedOn(e.target.value)} />
      <label htmlFor="frac">{t("report.fraction")}</label>
      <select id="frac" value={fraction} onChange={(e) => setFraction(e.target.value)}>
        {["unknown", "under_quarter", "quarter_half", "over_half"].map((v) => (
          <option key={v} value={v}>
            {t(`fraction.${v}`)}
          </option>
        ))}
      </select>
      <label htmlFor="started">{t("report.when_started")}</label>
      <select id="started" value={started} onChange={(e) => setStarted(e.target.value)}>
        {["unknown", "this_week", "one_to_two_weeks", "more_than_two_weeks"].map((v) => (
          <option key={v} value={v}>
            {t(`started.${v}`)}
          </option>
        ))}
      </select>
      <label htmlFor="irr">{t("report.irrigated_recently")}</label>
      <select id="irr" value={irrigated} onChange={(e) => setIrrigated(e.target.value)}>
        {["unknown", "yes", "no"].map((v) => (
          <option key={v} value={v}>
            {t(`answer.${v}`)}
          </option>
        ))}
      </select>
      <label htmlFor="desc">{t("report.description")}</label>
      <textarea id="desc" rows={4} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
      <label htmlFor="photos">{t("report.photos")}</label>
      <input id="photos" type="file" accept="image/jpeg,image/png" capture="environment" multiple onChange={(e) => setPhotos(e.target.files)} />
      <p className="small muted">{t("report.photo_privacy")}</p>
      <label className="check">
        <input type="checkbox" checked={expert} onChange={(e) => setExpert(e.target.checked)} />
        <span>
          <strong>{t("report.ask_expert")}</strong>
          <br />
          <span className="small muted">{t("consent.expert_review_help")}</span>
        </span>
      </label>
      <ErrorBox error={error} />
      <button type="submit" disabled={busy}>
        {busy ? t("common.working") : t("report.submit")}
      </button>
    </form>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["farmer"]}>
      <ReportForm />
    </RequireRole>
  );
}
