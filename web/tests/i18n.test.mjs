// Every translation key referenced in the UI must exist in en.json; other locales may
// only contain keys that exist in en.json; placeholders must match the English ones.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const en = JSON.parse(readFileSync(join(root, "locales/en.json"), "utf8"));

function files(dir) {
  return readdirSync(dir).flatMap((f) => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : p.endsWith(".tsx") || p.endsWith(".ts") ? [p] : [];
  });
}

test("static keys used in code exist in en.json", () => {
  const missing = new Set();
  for (const f of [...files(join(root, "app")), ...files(join(root, "components")), ...files(join(root, "lib"))]) {
    for (const m of readFileSync(f, "utf8").matchAll(/\bt\(\s*"([a-zA-Z0-9_.]+)"/g)) if (!(m[1] in en)) missing.add(m[1]);
  }
  assert.deepEqual([...missing], []);
});

test("dynamic key families are covered", () => {
  const families = {
    "risk.": ["insufficient_evidence", "normal_for_reference_period", "watch", "elevated_risk", "expert_review_recommended", "verified_stress", "resolved"],
    "risk_help.": ["insufficient_evidence", "normal_for_reference_period", "watch", "elevated_risk", "expert_review_recommended", "verified_stress", "resolved"],
    "freshness.": ["current", "stale", "unavailable"],
    "symptom.": ["wilting", "yellowing", "unusual_growth", "waterlogging", "pest_or_disease", "irrigation_problem", "other"],
    "case.": ["open", "assigned", "info_requested", "inspection_scheduled", "verified", "closed"],
    "job.": ["running", "succeeded", "partial", "failed"],
    "source_status.": ["live_tested", "implemented_untested", "not_configured", "unavailable", "manual_entry", "fixture_only"],
    "check.": ["crop_season_known", "sowing_date_known", "pixel_is_cropland", "vegetation_available", "vegetation_fresh", "vegetation_reference_sufficient", "vegetation_quality", "field_resolved_by_pixels", "weather_available", "weather_fresh", "independent_indicators", "model_validated", "guidance_available"],
  };
  const missing = [];
  for (const [p, ks] of Object.entries(families)) for (const k of ks) if (!(p + k in en)) missing.push(p + k);
  assert.deepEqual(missing, []);
});

test("backend explanation keys exist", () => {
  const engine = readFileSync(join(root, "../backend/croppulse/risk/engine.py"), "utf8");
  const keys = new Set([...engine.matchAll(/"(expl_[a-z0-9_]+)"/g)].map((m) => m[1]));
  const details = new Set([...engine.matchAll(/Check\(\s*"[a-z_]+",[^,]+,\s*"[a-z]+",\s*"([a-z_]+)"/g)].map((m) => m[1]));
  const missing = [...keys].filter((k) => !(k in en)).concat([...details].filter((d) => !(`check_detail.${d}` in en)));
  assert.deepEqual(missing, []);
  assert.ok(keys.size >= 15);
});

for (const lang of ["hi", "mr"]) {
  test(`${lang}.json keys and placeholders match en.json`, () => {
    const d = JSON.parse(readFileSync(join(root, `locales/${lang}.json`), "utf8"));
    assert.equal(d["_meta.review_status"], "unreviewed", "translations must stay marked unreviewed until reviewed");
    for (const [k, v] of Object.entries(d)) {
      if (k.startsWith("_meta")) continue;
      assert.ok(k in en, `${lang}: unknown key ${k}`);
      const ph = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort().join(",");
      assert.equal(ph(v), ph(en[k]), `${lang}: placeholder mismatch in ${k}`);
    }
  });
}
