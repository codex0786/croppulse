from __future__ import annotations

from croppulse.db import utcnow
from croppulse.guidance.library import render, render_unreviewed_translation
from croppulse.models import RiskAssessment
from croppulse.schemas import AssessmentOut, GuidanceOut


def assessment_out(ra: RiskAssessment, language: str = "en") -> AssessmentOut:
    out = AssessmentOut.model_validate(ra)
    out.is_expired = ra.expires_at <= utcnow()
    guidance: list[GuidanceOut] = []
    for gid in ra.guidance_ids:
        g = render(gid, language)
        if g is None:
            continue  # unapproved guidance is never shown
        guidance.append(
            GuidanceOut(
                id=g.guidance_id,
                language=g.language,
                body=g.body,
                translation_pending=g.translation_pending,
                unreviewed_translation=render_unreviewed_translation(gid, language) if g.translation_pending else None,
                source_org=g.source_org,
                source_ref=g.source_ref,
                limitations=g.limitations,
            )
        )
    out.guidance = guidance
    return out
