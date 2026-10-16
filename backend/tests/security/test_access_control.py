"""Authorisation, cross-organisation isolation, privilege escalation, input validation."""

import io
import logging

import pytest

from croppulse.enums import ConsentPurpose, Role
from croppulse.security import issue_token
from tests.conftest import field_payload


@pytest.fixture
def setup(client, actors):
    farmer, fh = actors.user(Role.farmer, "owner@pilot.croppulse.in", actors.org)
    other, oh = actors.user(Role.farmer, "other@pilot.croppulse.in", actors.org)
    agro_a, ah = actors.user(Role.agronomist, "agro-a@pilot.croppulse.in", actors.org)
    agro_b, bh = actors.user(Role.agronomist, "agro-b@pilot.croppulse.in", actors.org_b)
    fpo_a, ph = actors.user(Role.fpo_manager, "fpo-a@pilot.croppulse.in", actors.org)
    analyst, rh = actors.user(Role.regional_analyst, "analyst@pilot.croppulse.in")
    admin, adh = actors.user(Role.admin, "admin@pilot.croppulse.in")
    r = client.post("/api/v1/fields", json=field_payload(share_with_organization=False), headers=fh)
    assert r.status_code == 201, r.text
    return {"field": r.json()["id"], "fh": fh, "oh": oh, "ah": ah, "bh": bh, "ph": ph, "rh": rh, "adh": adh, "farmer": farmer}


def test_missing_and_invalid_authentication(client, setup):
    fid = setup["field"]
    assert client.get(f"/api/v1/fields/{fid}").status_code == 401
    assert client.get(f"/api/v1/fields/{fid}", headers={"Authorization": "Bearer v1.x.1.y"}).status_code == 401
    expired, _ = issue_token(setup["farmer"].id, ttl_minutes=-1)
    assert client.get(f"/api/v1/fields/{fid}", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    forged = expired.rsplit(".", 1)[0].replace(".-", ".") + ".AAAA"
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


@pytest.mark.parametrize("who", ["oh", "ah", "bh", "ph", "rh"])
def test_other_users_cannot_read_private_field(client, setup, who):
    fid = setup["field"]
    for path in ("", "/vegetation", "/weather", "/assessments/latest", "/reports"):
        r = client.get(f"/api/v1/fields/{fid}{path}", headers=setup[who])
        assert r.status_code == 404, (who, path, r.status_code)  # 404, not 403: no enumeration


def test_org_sharing_requires_consent_and_stays_in_org(client, setup, session, actors):
    from croppulse.governance import record_consent

    fid = setup["field"]
    assert client.get(f"/api/v1/fields/{fid}", headers=setup["ah"]).status_code == 404
    record_consent(session, setup["farmer"].id, ConsentPurpose.share_with_organization, True)
    session.commit()
    assert client.get(f"/api/v1/fields/{fid}", headers=setup["ah"]).status_code == 200
    assert client.get(f"/api/v1/fields/{fid}", headers=setup["ph"]).status_code == 200
    assert client.get(f"/api/v1/fields/{fid}", headers=setup["bh"]).status_code == 404  # other org
    # consent withdrawn → access removed
    record_consent(session, setup["farmer"].id, ConsentPurpose.share_with_organization, False)
    session.commit()
    assert client.get(f"/api/v1/fields/{fid}", headers=setup["ah"]).status_code == 404


def test_non_owner_cannot_modify(client, setup, session):
    from croppulse.governance import record_consent

    record_consent(session, setup["farmer"].id, ConsentPurpose.share_with_organization, True)
    session.commit()
    fid = setup["field"]
    assert client.delete(f"/api/v1/fields/{fid}", headers=setup["ah"]).status_code == 403
    assert (
        client.put(f"/api/v1/fields/{fid}/boundary", json={"geometry": {"type": "Point", "coordinates": [75.9, 19.95]}}, headers=setup["ph"]).status_code == 403
    )
    assert client.post(f"/api/v1/fields/{fid}/reports", json={"symptoms": ["wilting"], "observed_on": "2026-09-01"}, headers=setup["ah"]).status_code == 403


def test_privilege_escalation_blocked(client, setup):
    # self-registration can only create farmers, even if the body says otherwise
    r = client.post("/api/v1/auth/register", json={"email": "sneaky@pilot.croppulse.in", "password": "long-enough-pass", "display_name": "x", "role": "admin"})
    assert r.status_code == 201 and r.json()["role"] == "farmer"
    for path, method in [("/api/v1/admin/jobs", "get"), ("/api/v1/admin/audit", "get"), ("/api/v1/cases", "get"), ("/api/v1/regional/summary", "get")]:
        assert getattr(client, method)(path, headers=setup["fh"]).status_code == 403
    adv = {
        "source_org": "IMD",
        "source_url": "https://mausam.imd.gov.in/",
        "kind": "heat_warning",
        "title": "t",
        "body": "b",
        "districts": ["Jalna"],
        "issued_at": "2026-10-01T00:00:00Z",
        "valid_until": "2026-10-03T00:00:00Z",
    }
    assert client.post("/api/v1/admin/advisories", json=adv, headers=setup["ah"]).status_code == 403
    assert client.post("/api/v1/fields", json=field_payload(), headers=setup["ah"]).status_code == 403  # only farmers register fields


def test_admin_cannot_verify_cases_and_regional_has_no_identifiers(client, setup, session):
    from croppulse.governance import record_consent

    r = client.post(
        f"/api/v1/fields/{setup['field']}/reports", json={"symptoms": ["yellowing"], "observed_on": "2026-09-01", "request_expert": True}, headers=setup["fh"]
    )
    case_id = r.json()["case_id"]
    v = {"finding": "stress_confirmed", "observed_on": "2026-09-02", "method": "field_inspection"}
    assert client.post(f"/api/v1/cases/{case_id}/verify", json=v, headers=setup["adh"]).status_code == 403
    assert client.post(f"/api/v1/cases/{case_id}/verify", json=v, headers=setup["bh"]).status_code == 404  # other org
    record_consent(session, setup["farmer"].id, ConsentPurpose.aggregated_research, True)
    session.commit()
    body = client.get("/api/v1/regional/summary", headers=setup["rh"]).text
    assert setup["field"] not in body and "Synthetic test field" not in body and "19.95" not in body


def test_malformed_requests_do_not_echo_input(client, setup):
    r = client.post("/api/v1/fields", content=b"{not json", headers={**setup["fh"], "Content-Type": "application/json"})
    assert r.status_code == 422
    r = client.post("/api/v1/fields", json=field_payload(geometry={"type": "Point", "coordinates": [75.987654, 91.0]}), headers=setup["fh"])
    assert r.status_code == 422 and "75.987654" not in r.text
    r = client.post("/api/v1/auth/login", json={"email": "owner@pilot.croppulse.in", "password": 123})
    assert r.status_code == 422 and "123" not in r.text.replace("422", "")
    r = client.post(f"/api/v1/fields/{setup['field']}/reports", json={"symptoms": ["teleportation"], "observed_on": "2026-09-01"}, headers=setup["fh"])
    assert r.status_code == 422
    r = client.post(f"/api/v1/fields/{setup['field']}/reports", json={"symptoms": ["wilting"], "observed_on": "2999-01-01"}, headers=setup["fh"])
    assert r.status_code == 422


def test_invalid_upload_rejected_and_ownership_enforced(client, setup):
    r = client.post(f"/api/v1/fields/{setup['field']}/reports", json={"symptoms": ["wilting"], "observed_on": "2026-09-01"}, headers=setup["fh"])
    rid = r.json()["id"]
    bad = client.post(f"/api/v1/reports/{rid}/photos", files={"file": ("x.jpg", io.BytesIO(b"<script>alert(1)</script>"), "image/jpeg")}, headers=setup["fh"])
    assert bad.status_code == 422
    jpg = b"\xff\xd8\xff\xe1\x00\x0cExif\x00\x00GPS!\xff\xda\x00\x02data\xff\xd9"
    assert client.post(f"/api/v1/reports/{rid}/photos", files={"file": ("x.jpg", io.BytesIO(jpg), "image/jpeg")}, headers=setup["oh"]).status_code == 404
    ok = client.post(f"/api/v1/reports/{rid}/photos", files={"file": ("x.png", io.BytesIO(jpg), "image/png")}, headers=setup["fh"])
    assert ok.status_code == 201 and ok.json()["content_type"] == "image/jpeg" and ok.json()["metadata_stripped"]


def test_login_rate_limit(client, setup, monkeypatch):
    from croppulse.config import get_settings

    monkeypatch.setattr(get_settings(), "login_rate_limit_per_minute", 3)
    codes = [client.post("/api/v1/auth/login", json={"email": "owner@pilot.croppulse.in", "password": "wrong-password"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]


def test_logs_contain_no_secrets_or_coordinates(client, actors, caplog):
    from croppulse.logging_setup import JsonFormatter

    _, h = actors.user(Role.farmer, "logcheck@pilot.croppulse.in", actors.org)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logging.getLogger().addHandler(handler)
    try:
        client.post("/api/v1/auth/login", json={"email": "logcheck@pilot.croppulse.in", "password": "correct-horse-battery"})
        client.post("/api/v1/fields", json=field_payload(lat=19.951234, lon=75.912345), headers=h)
    finally:
        logging.getLogger().removeHandler(handler)
    out = stream.getvalue()
    assert out  # something was logged
    for s in ("correct-horse-battery", "19.951234", "75.912345", h["Authorization"].split()[1]):
        assert s not in out


def test_health_endpoints_do_not_leak_internals(client):
    h = client.get("/health")
    assert h.json() == {"status": "ok"}
    r = client.get("/ready")
    assert r.status_code == 200 and "sqlite" not in r.text and "password" not in r.text
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_server_errors_carry_cors_headers(client, actors, monkeypatch):
    from croppulse.api.routers import fields as fields_router

    _, h = actors.user(Role.farmer, "cors@pilot.croppulse.in", actors.org)
    monkeypatch.setattr(fields_router, "_calendar", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    r = client.get("/api/v1/fields/reference-data", headers={**h, "Origin": "http://localhost:3000"})
    assert r.status_code == 500 and r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "boom" not in r.text
