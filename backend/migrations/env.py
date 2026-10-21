"""Alembic environment: the database URL comes from CropPulse settings, never from alembic.ini."""

from __future__ import annotations

from alembic import context

from croppulse import models  # noqa: F401  (register tables)
from croppulse.config import get_settings
from croppulse.db import Base, make_engine

target_metadata = Base.metadata


def include_object(obj: object, name: str, type_: str, reflected: bool, compare_to: object | None) -> bool:
    """Ignore database-owned tables, such as PostGIS system tables.

    Autogenerate should compare only tables declared by CropPulse models. A
    PostGIS-enabled database contains extension-owned relations in public;
    treating those as application drift produces false removals in alembic
    check even though CropPulse does not own those relations.
    """
    if type_ == "table" and reflected and compare_to is None:
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
