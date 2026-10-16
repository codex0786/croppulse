import io
import json
import logging

from croppulse.enums import RiskState
from croppulse.guidance.library import approved_ids_for_state, render
from croppulse.logging_setup import JsonFormatter, log, redact


def test_redaction_of_secrets_and_coordinates():
    out = redact({"password": "x", "geometry": {"type": "Point"}, "note": "Bearer abc.def.ghi at 19.95123,75.90123", "n": 3})
    assert out["password"] == "[REDACTED]" and out["geometry"] == "[REDACTED]"
    assert "19.95123" not in out["note"] and "abc.def" not in out["note"] and out["n"] == 3


def test_json_formatter_never_emits_coordinates_or_tokens():
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(JsonFormatter())
    lg = logging.getLogger("t")
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    log(
        lg,
        logging.INFO,
        "fetch https://x/api?latitude=19.88123&longitude=75.34123 token v1.0123456789abcdef0123456789abcdef.1999999999.sig_x",
        lat=19.88123,
        email="a@b.in",
    )
    line = buf.getvalue()
    json.loads(line)
    for secret in ("19.88123", "75.34123", "0123456789abcdef0123456789abcdef", "a@b.in"):
        assert secret not in line


def test_unapproved_guidance_is_never_rendered():
    assert render("agronomic_template_example", "en") is None
    for s in RiskState:
        assert "agronomic_template_example" not in approved_ids_for_state(s)


def test_unreviewed_translation_falls_back_to_english():
    g = render("next_step_watch", "mr")
    assert g is not None and g.translation_pending and g.language == "en" and "does not establish its cause" in g.body
