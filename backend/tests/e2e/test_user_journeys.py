"""End-to-end journeys through the HTTP API with SYNTHETIC source fixtures.

Covers: registration → field → timestamped vegetation chart → assessment (or abstention)
→ farmer report → expert review → verified finding → alert gating → regional aggregate
→ unauthorized access → visible degraded state during a source outage.
"""

from datetime import timedelta

from croppulse.db import utcnow
from croppulse.enums import ConsentPurpose, Role
from tests.conftest import field_payload


def _register_and_login(client, email, org_id=None):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "a-long-test-password", "display_name": "Synthetic Farmer", "preferred_language": "mr", "organization_id": org_id},
    )
    assert r.status_code == 201, r.text
    t = client.post("/api/v1/auth/login", json={"email": email, "password": "a-long-test-password"}).json()["access_token"]
    return {"Authorization": f"Bearer {t}"}


def test_full_farmer_to_expert_journey(client, actors, world, session):
    world.anomaly_year = utcnow().year
    world.anomaly_from = utcnow().date() - timedelta(days=90)
    world.rain_scale_target_year = 0.0
    agro, ah = actors.user(Role.agronomist, "agronomist@pilot.croppulse.in", actors.org)
    analyst, rh = actors.user(Role.regional_analyst, "analyst@pilot.croppulse.in")

    # 1. farmer registers, consents and registers a field
    fh = _register_and_login(client, "farmer@pilot.croppulse.in", actors.org.id)
    for p in ("expert_review", "aggregated_research"):
        assert client.post("/api/v1/me/consents", json={"purpose": p, "granted": True}, headers=fh).status_code == 200
    chk = client.post("/api/v1/fields/validate-boundary", json={"geometry": field_payload()["geometry"]}, headers=fh).json()
    assert chk["valid"] and chk["area_ha"] > 50
    r = client.post("/api/v1/fields", json=field_payload(), headers=fh)
    assert r.status_code == 201
    fid = r.json()["id"]

    # Before data arrives: explicit absence, never a fabricated assessment
    assert client.get(f"/api/v1/fields/{fid}/assessments/latest", headers=fh).json() is None
    assert client.get(f"/api/v1/fields/{fid}/vegetation", headers=fh).json()["points"] == []

    # 2. refresh (background task runs synchronously in TestClient)
    assert client.post(f"/api/v1/fields/{fid}/refresh", headers=fh).json()["status"] == "queued"
    jobs = client.get(f"/api/v1/fields/{fid}/jobs", headers=fh).json()
    assert {j["source_id"] for j in jobs} == {"modis_mod13q1", "modis_mcd12q1", "nasa_power_daily"}
    veg = client.get(f"/api/v1/fields/{fid}/vegetation", headers=fh).json()
    assert veg["is_synthetic"] and veg["data_kind"] == "observed" and veg["unit"] == "dimensionless"
    p = veg["points"][-1]
    assert p["period_start"] < p["period_end"] and p["reference_n"] >= 8 and p["published_at"]
    wx = client.get(f"/api/v1/fields/{fid}/weather", headers=fh).json()
    assert wx["units"]["PRECTOTCORR"] == "mm/day" and wx["grid_cell"] and wx["last_valid_date"]

    # 3. assessment exists, is labelled synthetic, unvalidated and process-guidance only
    a = client.get(f"/api/v1/fields/{fid}/assessments/latest", headers=fh).json()
    assert a["state"] == "elevated_risk" and a["is_synthetic"] and not a["model_validated"] and a["uncertainty"]["probability"] is None
    assert a["guidance"] and a["guidance"][0]["translation_pending"] and a["guidance"][0]["unreviewed_translation"]
    alerts = client.get("/api/v1/alerts", headers=fh).json()
    assert len(alerts) == 1 and alerts[0]["requires_expert"]

    # escalation created a case for the farmer's organisation (expert_review consent given)
    queue = client.get("/api/v1/cases", headers=ah).json()
    assert len(queue) == 1 and queue[0]["origin"] == "assessment_escalation"

    # 4. farmer report joins the case and moves state to expert_review_recommended
    rep = client.post(
        f"/api/v1/fields/{fid}/reports",
        json={"symptoms": ["wilting", "yellowing"], "observed_on": utcnow().date().isoformat(), "request_expert": True, "client_ref": "offline-123"},
        headers=fh,
    ).json()
    again = client.post(
        f"/api/v1/fields/{fid}/reports", json={"symptoms": ["wilting"], "observed_on": utcnow().date().isoformat(), "client_ref": "offline-123"}, headers=fh
    ).json()
    assert again["id"] == rep["id"]  # offline replay idempotent
    a2 = client.post(f"/api/v1/fields/{fid}/assess", headers=fh).json()
    assert a2["state"] == "expert_review_recommended"

    # 5. expert reviews
    case_id = queue[0]["id"]
    assert client.post(f"/api/v1/cases/{case_id}/assign", json={}, headers=ah).json()["status"] == "assigned"
    detail = client.get(f"/api/v1/cases/{case_id}", headers=ah).json()
    assert detail["report"]["symptoms"] == ["wilting", "yellowing"] and detail["assessment"]["model_version"]
    assert any(e["authored_by"] == "system" for e in detail["events"])
    client.post(
        f"/api/v1/cases/{case_id}/events",
        json={"kind": "inspection_scheduled", "body": "Visit planned", "scheduled_for": utcnow().date().isoformat()},
        headers=ah,
    )
    client.post(
        f"/api/v1/cases/{case_id}/events",
        json={"kind": "recommendation", "body": "Expert recommendation text", "source_ref": "https://example.org/package-of-practices"},
        headers=ah,
    )

    # 6. verified finding (label) recorded with identity and time
    vo = client.post(
        f"/api/v1/cases/{case_id}/verify",
        json={
            "finding": "stress_confirmed",
            "suspected_cause": "moisture_stress",
            "observed_on": utcnow().date().isoformat(),
            "method": "field_inspection",
            "notes": "checked",
        },
        headers=ah,
    )
    assert vo.status_code == 201 and vo.json()["verified_by"] == agro.id
    assert (
        client.post(
            f"/api/v1/cases/{case_id}/verify", json={"finding": "false_alarm", "observed_on": utcnow().date().isoformat(), "method": "phone_call"}, headers=ah
        ).status_code
        == 409
    )
    recs = client.get(f"/api/v1/fields/{fid}/recommendations", headers=fh).json()
    assert {r["kind"] for r in recs} >= {"recommendation", "verification"} and all(r["data_kind"] in ("expert_authored", "expert_verified") for r in recs)
    a3 = client.post(f"/api/v1/fields/{fid}/assess", headers=fh).json()
    assert a3["state"] == "verified_stress"
    assert client.post(f"/api/v1/cases/{case_id}/close", headers=ah).json()["status"] == "closed"
    assert client.post(f"/api/v1/cases/{case_id}/reopen", headers=ah).json()["status"] == "assigned"

    # 8. regional user sees suppressed aggregate (only one consenting field < k=3)
    reg = client.get("/api/v1/regional/summary", headers=rh).json()
    assert reg["consenting_fields"] == 1 and reg["districts"][0]["suppressed"] and reg["grid_cells"] == []


def test_insufficient_evidence_abstains_and_no_alert(client, actors, world):
    world.modis_fail = True
    world.power_fail = True
    fh = _register_and_login(client, "f2@pilot.croppulse.in", actors.org.id)
    fid = client.post("/api/v1/fields", json=field_payload(), headers=fh).json()["id"]
    client.post(f"/api/v1/fields/{fid}/refresh", headers=fh)
    a = client.get(f"/api/v1/fields/{fid}/assessments/latest", headers=fh).json()
    assert a["state"] == "insufficient_evidence" and a["freshness"]["vegetation"]["status"] == "unavailable"
    assert client.get("/api/v1/alerts", headers=fh).json() == []
    # 10. outage is visible in source status
    src = {s["id"]: s for s in client.get("/api/v1/sources").json()}
    assert src["modis_mod13q1"]["status"] == "unavailable" and src["modis_mod13q1"]["last_error"]
    assert src["gpm_imerg"]["status"] == "not_configured" and src["smap_l4"]["status"] == "not_configured"


def test_vegetation_outage_with_weather_never_reads_healthy(client, actors, world):
    world.modis_fail = True
    fh = _register_and_login(client, "f3@pilot.croppulse.in", actors.org.id)
    fid = client.post("/api/v1/fields", json=field_payload(), headers=fh).json()["id"]
    client.post(f"/api/v1/fields/{fid}/refresh", headers=fh)
    a = client.get(f"/api/v1/fields/{fid}/assessments/latest", headers=fh).json()
    assert a["freshness"]["vegetation"]["status"] == "unavailable" and a["freshness"]["weather"]["status"] == "current"
    assert a["state"] in ("insufficient_evidence", "watch")  # weather-only signal at most → watch; never "normal"
    assert any(e["key"] == "expl_vegetation_unavailable" for e in a["explanations"])


def test_regional_aggregate_with_enough_fields(client, actors, world, session):

    _, rh = actors.user(Role.regional_analyst, "a@pilot.croppulse.in")
    for i in range(3):
        u, h = actors.user(Role.farmer, f"rf{i}@pilot.croppulse.in", actors.org, consents=(ConsentPurpose.aggregated_research,))
        fid = client.post("/api/v1/fields", json=field_payload(lat=19.95 + i * 0.01), headers=h).json()["id"]
        client.post(f"/api/v1/fields/{fid}/refresh", headers=h)
    reg = client.get("/api/v1/regional/summary", headers=rh).json()
    d = reg["districts"][0]
    assert not d["suppressed"] and d["fields"] == 3 and d["synthetic_fields"] == 3
    assert reg["grid_cells"] and reg["grid_cells"][0]["rain_30d"] is not None


def test_yield_disabled_and_openapi(client):
    r = client.get("/api/v1/yield")
    assert r.status_code == 501 and "disabled" in r.json()["detail"]
    assert "/api/v1/fields" in client.get("/openapi.json").json()["paths"]
