"""UTC-naive 数据库时间默认值契约。"""

from pathlib import Path

from sqlalchemy import DateTime

from app.models.entities import Base


UTC_DEFAULT_SQL = "timezone('UTC', CURRENT_TIMESTAMP)"


def test_datetime_server_defaults_are_explicitly_utc_naive():
    defaults = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, DateTime) and column.server_default is not None:
                defaults.append((f"{table.name}.{column.name}", str(column.server_default.arg)))

    assert defaults
    assert all(default_sql == UTC_DEFAULT_SQL for _, default_sql in defaults), defaults


def test_business_migrations_never_use_session_local_now_for_naive_timestamps():
    versions_dir = Path(__file__).parents[2] / "alembic" / "versions"
    migration_002 = (versions_dir / "002_business_integrity.py").read_text(encoding="utf-8")
    migration_003 = (versions_dir / "003_schema_alignment.py").read_text(encoding="utf-8")

    assert "coalesce(min(chunk.created_at), timezone('UTC', CURRENT_TIMESTAMP))" in migration_002
    assert "NOW_DEFAULT = sa.text(\"timezone('UTC', CURRENT_TIMESTAMP)\")" in migration_003
    assert "COALESCE(created_at, CURRENT_TIMESTAMP)" not in migration_003
    assert "COALESCE(updated_at, CURRENT_TIMESTAMP)" not in migration_003
