"""Alembic environment: the database URL comes from CropPulse settings, never from alembic.ini."""

from __future__ import annotations

from alembic import context

from croppulse import models  # noqa: F401  (register tables)
from croppulse.config import get_settings
from croppulse.db import Base, make_engine

target_metadata = Base.metadata


def include_object(obj: object, name: str, type_: str, reflected: bool, compare_to: object | None) -> bool:
    """Ignore database-owned tables and their objects during autogeneration.

    PostGIS installs extension-owned relations into public. They are not
    CropPulse models and must not be reported as application schema drift.
    """
    if not reflected or compare_to is not None:
        return True

    if type_ == "table":
        return False

    # Reflected indexes/constraints/columns belong to their parent table.
    # Skip them when that table is not part of CropPulse's model metadata.
    parent_table = getattr(obj, "table", None)
    if parent_table is not None:
        key = f"{parent_table.schema}.{parent_table.name}" if parent_table.schema else parent_table.name
        if key not in target_metadata.tables and parent_table.name not in target_metadata.tables:
            return False

    return True


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = context.config.attributes.get("database_url") or get_settings().database_url
    engine = make_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
