"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { RequireRole } from "@/components/AppShell";
import { DataQualityWarning, ErrorBox } from "@/components/Status";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const MapView = dynamic(() => import("@/components/MapView"), { ssr: false });

interface RefData {
  crops: Record<string, string[]>;
  districts: string[];
  crop_calendar_reviewed: boolean;
  irrigation: string[];
}
interface Check {
  valid: boolean;
  error: string | null;
  area_ha: number | null;
  kind: string | null;
  warnings: string[];
}

function NewField() {
  const { t, fmtNum } = useI18n();
  const router = useRouter();
  const [ref, setRef] = useState<RefData | null>(null);
  const [step, setStep] = useState(1);
  const [mode, setMode] = useState<"draw" | "point" | "geojson">("draw");
  const [vertices, setVertices] = useState<[number, number][]>([]);
  const [point, setPoint] = useState<[number, number] | null>(null);
  const [geojsonText, setGeojsonText] = useState("");
  const [check, setCheck] = useState<Check | null>(null);
  const [name, setName] = useState("");
  const [district, setDistrict] = useState("");
  const [crop, setCrop] = useState("");
  const [season, setSeason] = useState("");
  const [year, setYear] = useState(new Date().getFullYear());
  const [sowing, setSowing] = useState("");
  const [sowingUncertain, setSowingUncertain] = useState(false);
  const [irrigation, setIrrigation] = useState("unknown");
  const [share, setShare] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<RefData>("/api/v1/fields/reference-data").then(setRef).catch(setError);
  }, []);

  const geometry = (): GeoJSON.Geometry | null => {
    if (mode === "draw" && vertices.length >= 3) {
      const ring = vertices.map(([la, lo]) => [lo, la]);
      return { type: "Polygon", coordinates: [[...ring, ring[0]]] };
    }
    if (mode === "point" && point) return { type: "Point", coordinates: [point[1], point[0]] };
    if (mode === "geojson" && geojsonText.trim()) {
      try {
        const g = JSON.parse(geojsonText);
        return g.type === "Feature" ? g.geometry : g.type === "FeatureCollection" ? g.features?.[0]?.geometry : g;
      } catch {
        return null;
      }
    }
    return null;
  };

  const validate = async () => {
    setError(null);
    const g = geometry();
    if (!g) {
      setCheck({ valid: false, error: t("register_field.need_boundary"), area_ha: null, kind: null, warnings: [] });
      return;
    }
    try {
      setCheck(await api<Check>("/api/v1/fields/validate-boundary", { method: "POST", body: { geometry: g } }));
    } catch (e) {
      setError(e);
    }
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const f = await api<{ id: string }>("/api/v1/fields", {
        method: "POST",
        body: {
          name,
          district,
          geometry: geometry(),
          share_with_organization: share,
          season: { crop, season, season_year: year, sowing_date: sowing || null, sowing_date_uncertain: sowingUncertain || !sowing, irrigation },
        },
      });
      await api(`/api/v1/fields/${f.id}/refresh`, { method: "POST" }).catch(() => undefined);
      router.push(`/farmer/fields/${f.id}?new=1`);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const steps = ["register_field.step_location", "register_field.step_crop", "register_field.step_consent"];
  return (
    <>
      <h1>{t("register_field.title")}</h1>
      <ol className="steps" aria-label={t("register_field.progress")}>
        {steps.map((s, i) => (
          <li key={s} className={step === i + 1 ? "current" : ""} aria-current={step === i + 1 ? "step" : undefined}>
            {i + 1}. {t(s)}
          </li>
        ))}
      </ol>
      <ErrorBox error={error} />

      {step === 1 ? (
        <div className="card">
          <fieldset>
            <legend>{t("register_field.how")}</legend>
            {(["draw", "point", "geojson"] as const).map((m) => (
              <label key={m} className="check">
                <input type="radio" name="mode" checked={mode === m} onChange={() => { setMode(m); setCheck(null); }} />
                {t(`register_field.mode_${m}`)}
              </label>
            ))}
          </fieldset>
          {mode === "draw" ? (
            <>
              <MapView draw vertices={vertices} onVerticesChange={(v) => { setVertices(v); setCheck(null); }} zoom={8} height={340} ariaLabel={t("map.draw_aria")} />
              <div className="row">
                <button type="button" className="secondary" onClick={() => setVertices(vertices.slice(0, -1))} disabled={!vertices.length}>
                  {t("register_field.undo")}
                </button>
                <button type="button" className="secondary" onClick={() => setVertices([])} disabled={!vertices.length}>
                  {t("register_field.clear")}
                </button>
                <span className="small muted">{t("register_field.vertices", { n: vertices.length })}</span>
              </div>
            </>
          ) : null}
          {mode === "point" ? (
            <div>
              <button
                type="button"
                className="secondary"
                onClick={() =>
                  navigator.geolocation?.getCurrentPosition(
                    (pos) => { setPoint([pos.coords.latitude, pos.coords.longitude]); setCheck(null); },
                    () => setError(new Error(t("register_field.location_denied"))),
                    { enableHighAccuracy: true, timeout: 15000 },
                  )
                }
              >
                {t("register_field.use_location")}
              </button>
              <p className="small muted">{t("register_field.point_note")}</p>
              {point ? <MapView shapes={[{ geometry: { type: "Point", coordinates: [point[1], point[0]] } }]} zoom={14} ariaLabel={t("map.field_aria")} /> : null}
            </div>
          ) : null}
          {mode === "geojson" ? (
            <>
              <label htmlFor="gj">{t("register_field.paste_geojson")}</label>
              <textarea id="gj" rows={5} value={geojsonText} onChange={(e) => { setGeojsonText(e.target.value); setCheck(null); }} />
            </>
          ) : null}
          <p>
            <button type="button" className="secondary" onClick={validate}>
              {t("register_field.check_boundary")}
            </button>
          </p>
          {check ? (
            check.valid ? (
              <div className="note">
                <p>{check.area_ha ? t("register_field.valid_area", { ha: fmtNum(check.area_ha, 2) }) : t("register_field.valid_point")}</p>
                {check.warnings.map((w) => (
                  <DataQualityWarning key={w}>{t(`geom_warning.${w}`)}</DataQualityWarning>
                ))}
              </div>
            ) : (
              <div className="error">{check.error}</div>
            )
          ) : null}
          <button type="button" disabled={!check?.valid} onClick={() => setStep(2)}>
            {t("common.next")}
          </button>
        </div>
      ) : null}

      {step === 2 && ref ? (
        <form
          className="card"
          onSubmit={(e) => {
            e.preventDefault();
            setStep(3);
          }}
        >
          <label htmlFor="fname">{t("register_field.name")}</label>
          <input id="fname" required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} />
          <label htmlFor="district">{t("register_field.district")}</label>
          <select id="district" required value={district} onChange={(e) => setDistrict(e.target.value)}>
            <option value="">{t("common.choose")}</option>
            {ref.districts.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <label htmlFor="crop">{t("register_field.crop")}</label>
          <select id="crop" required value={crop} onChange={(e) => { setCrop(e.target.value); setSeason(""); }}>
            <option value="">{t("common.choose")}</option>
            {Object.keys(ref.crops).map((c) => (
              <option key={c} value={c}>
                {t(`crop.${c}`)}
              </option>
            ))}
          </select>
          <label htmlFor="season">{t("register_field.season")}</label>
          <select id="season" required value={season} onChange={(e) => setSeason(e.target.value)} disabled={!crop}>
            <option value="">{t("common.choose")}</option>
            {(ref.crops[crop] ?? []).map((s) => (
              <option key={s} value={s}>
                {t(`season.${s}`)}
              </option>
            ))}
          </select>
          <label htmlFor="year">{t("register_field.season_year")}</label>
          <input id="year" type="number" min={2000} max={2100} required value={year} onChange={(e) => setYear(Number(e.target.value))} />
          <label htmlFor="sowing">{t("register_field.sowing")}</label>
          <input id="sowing" type="date" max={new Date().toISOString().slice(0, 10)} value={sowing} onChange={(e) => setSowing(e.target.value)} />
          <label className="check">
            <input type="checkbox" checked={sowingUncertain} onChange={(e) => setSowingUncertain(e.target.checked)} />
            {t("register_field.sowing_uncertain")}
          </label>
          <label htmlFor="irr">{t("register_field.irrigation")}</label>
          <select id="irr" value={irrigation} onChange={(e) => setIrrigation(e.target.value)}>
            {ref.irrigation.map((i) => (
              <option key={i} value={i}>
                {t(`irrigation.${i}`)}
              </option>
            ))}
          </select>
          {!ref.crop_calendar_reviewed ? <p className="small muted">{t("register_field.calendar_unreviewed")}</p> : null}
          <div className="row">
            <button type="button" className="secondary" onClick={() => setStep(1)}>
              {t("common.back")}
            </button>
            <button type="submit">{t("common.next")}</button>
          </div>
        </form>
      ) : null}

      {step === 3 ? (
        <div className="card">
          <h2>{t("register_field.data_title")}</h2>
          <ul>
            <li>{t("register_field.data_boundary")}</li>
            <li>{t("register_field.data_crop")}</li>
            <li>{t("register_field.data_sources")}</li>
            <li>{t("register_field.data_not_shared")}</li>
          </ul>
          <label className="check">
            <input type="checkbox" checked={share} onChange={(e) => setShare(e.target.checked)} />
            <span>
              <strong>{t("consent.share_with_organization")}</strong>
              <br />
              <span className="small muted">{t("consent.share_with_organization_help")}</span>
            </span>
          </label>
          <p className="small muted">{t("register_field.processing_time")}</p>
          <div className="row">
            <button type="button" className="secondary" onClick={() => setStep(2)}>
              {t("common.back")}
            </button>
            <button type="button" onClick={submit} disabled={busy}>
              {busy ? t("common.working") : t("register_field.submit")}
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}

export default function Page() {
  return (
    <RequireRole roles={["farmer"]}>
      <NewField />
    </RequireRole>
  );
}
