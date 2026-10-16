"""Helpers shared by report-generation scripts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


class SyntheticDataError(RuntimeError):
    """Raised when synthetic rows would enter a real-data scientific report."""


def assert_real_data(df: pd.DataFrame, what: str) -> None:
    if "is_synthetic" not in df.columns:
        raise SyntheticDataError(f"{what}: provenance column is_synthetic missing — refusing to report")
    if df["is_synthetic"].astype(bool).any():
        raise SyntheticDataError(f"{what}: contains synthetic rows — excluded from real-data reports")


def code_version(repo: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip() or "uncommitted"  # noqa: S603, S607
    except Exception:
        return "uncommitted"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_manifest(path: Path, entries: dict[str, Any]) -> None:
    entries = {"generated_at": datetime.now(UTC).isoformat(), **entries}
    path.write_text(json.dumps(entries, indent=2, default=str))
