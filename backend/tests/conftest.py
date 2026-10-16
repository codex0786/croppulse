"""Test configuration: isolated temp data dir + SQLite DB, synthetic transport, helpers."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_TMP = Path(tempfile.mkdtemp(prefix="croppulse-test-"))
os.environ.update(
    {
        "CROPPULSE_ENVIRONMENT": "test",
        "CROPPULSE_DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
        "CROPPULSE_DATA_DIR": str(_TMP / "data"),
        "CROPPULSE_UPLOAD_DIR": str(_TMP / "data" / "uploads"),
        "CROPPULSE_PASSWORD_HASH_ITERATIONS": "1000",
        "CROPPULSE_SECRET_KEY": "test-secret-key-not-for-production-0123456789",
        "CROPPULSE_HTTP_MAX_RETRIES": "2",
        "CROPPULSE_LOGIN_RATE_LIMIT_PER_MINUTE": "1000",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from croppulse.db import Base, get_engine, get_sessionmaker  # noqa: E402
from croppulse.enums import ConsentPurpose, Role  # noqa: E402
from croppulse.governance import record_consent  # noqa: E402
from croppulse.models import Organization, User  # noqa: E402
from croppulse.security import hash_password, issue_token, rate_limiter  # noqa: E402
from croppulse.sources import base as source_base  # noqa: E402
from tests.fixtures.synthetic import SyntheticWorld  # noqa: E402

RECORDED = Path(__file__).parent / "fixtures" / "recorded"


def pytest_sessionstart(session: Any) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    command.upgrade(cfg, "head")


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def clean_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr("time.sleep", lambda s: None)
    rate_limiter.reset()
    yield
    source_base.default_transport = None
    with get_engine().begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(delete(table))
    shutil.rmtree(_TMP / "data", ignore_errors=True)


@pytest.fixture
def world() -> Iterator[SyntheticWorld]:
    w = SyntheticWorld()
    source_base.default_transport = w.transport()
    yield w
    source_base.default_transport = None


@pytest.fixture
def session() -> Iterator[Any]:
    s = get_sessionmaker()()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def client() -> TestClient:
    from croppulse.api.main import app

    return TestClient(app)


class Actors:
    """Creates organisations and users of each role; returns auth headers."""

    def __init__(self, session: Any) -> None:
        self.s = session
        self.org = Organization(name="Synthetic FPO A", kind="fpo", state="Maharashtra", district="Jalna")
        self.org_b = Organization(name="Synthetic FPO B", kind="fpo", state="Maharashtra", district="Beed")
        session.add_all([self.org, self.org_b])
        session.commit()

    def user(self, role: Role, email: str, org: Organization | None = None, consents: tuple[ConsentPurpose, ...] = ()) -> tuple[User, dict[str, str]]:
        u = User(
            email=email,
            display_name=email.split("@")[0],
            password_hash=hash_password("correct-horse-battery", 1000),
            role=role,
            organization_id=org.id if org else None,
        )
        self.s.add(u)
        self.s.flush()
        record_consent(self.s, u.id, ConsentPurpose.core_service, True)
        for c in consents:
            record_consent(self.s, u.id, c, True)
        self.s.commit()
        token, _ = issue_token(u.id)
        return u, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def actors(session: Any) -> Actors:
    return Actors(session)


def field_payload(lat: float = 19.95, lon: float = 75.9, **overrides: Any) -> dict[str, Any]:
    from tests.fixtures.synthetic import square_polygon

    body = {
        "name": "Synthetic test field",
        "district": "Jalna",
        "geometry": square_polygon(lat, lon),
        "season": {"crop": "soybean", "season": "kharif", "season_year": 2026, "sowing_date": "2026-06-25", "irrigation": "rainfed"},
        "share_with_organization": True,
    }
    body.update(overrides)
    return body
