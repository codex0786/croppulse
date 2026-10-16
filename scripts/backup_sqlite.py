"""Consistent online backup of the development SQLite database (sqlite3 backup API)."""

import sqlite3
from datetime import UTC, datetime

from croppulse.config import get_settings

if __name__ == "__main__":
    s = get_settings()
    if not s.database_url.startswith("sqlite:///"):
        raise SystemExit("Not a SQLite database; use pg_dump (docs/OPERATIONS.md).")
    src_path = s.database_url.removeprefix("sqlite:///")
    out_dir = s.data_dir / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"croppulse-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.db"
    with sqlite3.connect(src_path) as src, sqlite3.connect(dest) as dst:
        src.backup(dst)
    print(dest)
