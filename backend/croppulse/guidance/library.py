"""Source-backed guidance library (config/guidance.yaml), separate from model outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from croppulse.config import get_settings, load_yaml
from croppulse.enums import ApprovalStatus, RiskState


@dataclass(frozen=True)
class GuidanceText:
    guidance_id: str
    language: str
    body: str
    translation_pending: bool
    source_org: str | None
    source_ref: str | None
    limitations: str


def _items() -> list[dict[str, Any]]:
    return list(load_yaml(str(get_settings().guidance_path))["items"])


def library_version() -> str:
    return str(load_yaml(str(get_settings().guidance_path))["version"])


def approved_ids_for_state(state: RiskState) -> list[str]:
    return [
        it["id"]
        for it in _items()
        if it["approval_status"] == ApprovalStatus.approved and state.value in it.get("applies_to_states", [])
    ]


def render(guidance_id: str, language: str) -> GuidanceText | None:
    """Return approved guidance text. Unapproved items return None (never shown to farmers).

    Unreviewed translations fall back to English and are flagged.
    """
    item = next((it for it in _items() if it["id"] == guidance_id), None)
    if item is None or item["approval_status"] != ApprovalStatus.approved:
        return None
    texts = item["text"]
    t = texts.get(language)
    pending = False
    if t is None or t.get("status") != "approved":
        pending = language != "en"
        t = texts["en"]
    return GuidanceText(guidance_id, language if not pending else "en", t["body"], pending, item.get("source_org"), item.get("source_ref"), item.get("limitations", ""))


def render_unreviewed_translation(guidance_id: str, language: str) -> str | None:
    """Unreviewed translation for display *next to* the English original, clearly labelled."""
    item = next((it for it in _items() if it["id"] == guidance_id), None)
    if item is None or item["approval_status"] != ApprovalStatus.approved:
        return None
    t = item["text"].get(language)
    return t["body"] if t else None
