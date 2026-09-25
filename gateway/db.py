"""Database engine/session. Works with SQLite (dev) and SQL Server (prod)."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    s = get_settings()
    kwargs: dict = {"pool_pre_ping": True, "future": True}
    if s.database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # SQL Server: bounded pool, fast_executemany for bulk imports.
        kwargs.update(pool_size=10, max_overflow=5, pool_recycle=1800)
        if s.database_url.startswith("mssql+pyodbc"):
            kwargs["fast_executemany"] = True
    engine = create_engine(s.database_url, **kwargs)
    if s.db_schema:
        engine = engine.execution_options(schema_translate_map={None: s.db_schema})
    if s.database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # enforce FKs in SQLite like SQL Server does
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, rolled back on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
