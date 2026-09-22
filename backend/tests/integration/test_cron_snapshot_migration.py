import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import LiteralString, cast

import psycopg
import pytest
from psycopg import errors, sql
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"


def _psycopg_url(database_url: str, database: str | None = None) -> str:
    url = make_url(database_url).set(drivername="postgresql", database=database)
    return url.render_as_string(hide_password=False)


@contextmanager
def _temporary_database() -> Iterator[str]:
    source_url = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get(
        "DATABASE_URL", DEFAULT_DATABASE_URL
    )
    source_database = make_url(source_url).database
    database = f"test_schema_{uuid.uuid4().hex}"
    admin_url = _psycopg_url(source_url, source_database)

    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))

    try:
        yield make_url(source_url).set(database=database).render_as_string(hide_password=False)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            connection.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def _alembic(database_url: str, *arguments: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    environment["DATABASE_URL_UNPOOLED"] = database_url
    subprocess.run(  # noqa: S603 - arguments are fixed test-controlled Alembic commands.
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _seed_0001(database_url: str) -> None:
    with psycopg.connect(_psycopg_url(database_url)) as connection:
        connection.execute(
            """
            INSERT INTO companies (id, name) VALUES (101, 'seed company');
            INSERT INTO users (id, email, password)
            VALUES (101, 'seed@example.com', 'hash');
            INSERT INTO marketers (id, user_id, name, company_id)
            VALUES (101, 101, 'seed marketer', 101);
            INSERT INTO agent_sessions (id, marketer_id, agent)
            VALUES (101, 101, 'parent');
            INSERT INTO campaigns (
                id, company_id, created_by_marketer_id, title,
                target_profile, background, objective, plan
            ) VALUES (101, 101, 101, 'title', 'target', 'background', 'objective', 'plan');
            INSERT INTO api_idempotency_requests (
                id, marketer_id, session_id, operation, idempotency_key,
                request_hash, status, execution_token, lease_expires_at
            ) VALUES
                (101, 101, 101, 'publish_x_post',
                 '00000000-0000-0000-0000-000000000101', repeat('a', 64),
                 'processing', '10000000-0000-0000-0000-000000000101', now()),
                (102, 101, 101, 'publish_x_post',
                 '00000000-0000-0000-0000-000000000102', repeat('b', 64),
                 'processing', '10000000-0000-0000-0000-000000000102', now()),
                (103, 101, 101, 'publish_x_post',
                 '00000000-0000-0000-0000-000000000103', repeat('c', 64),
                 'processing', '10000000-0000-0000-0000-000000000103', now());
            INSERT INTO posts (
                id, company_id, created_by_marketer_id, campaign_id,
                api_idempotency_request_id, body, x_post_id, published_at
            ) VALUES
                (101, 101, 101, 101, 101, 'pending', 'x-101', now()),
                (102, 101, 101, 101, 102, 'completed', 'x-102', now()),
                (103, 101, 101, 101, 103, 'failed', 'x-103', now());
            INSERT INTO post_metrics (
                post_id, scheduled_at, status, x_pv_count,
                landing_user_count, measured_at
            ) VALUES
                (101, now(), 'pending', NULL, NULL, NULL),
                (102, now(), 'completed', 20, 4, now()),
                (103, now(), 'failed', 8, NULL, NULL);
            """
        )


@pytest.fixture(scope="module")
def empty_database() -> Iterator[str]:
    with _temporary_database() as database_url:
        _alembic(database_url, "upgrade", "head")
        yield database_url


@pytest.fixture(scope="module")
def seeded_database() -> Iterator[str]:
    with _temporary_database() as database_url:
        _alembic(database_url, "upgrade", "0001")
        _seed_0001(database_url)
        _alembic(database_url, "upgrade", "head")
        yield database_url


def test_empty_database_upgrades_to_head(empty_database: str) -> None:
    with psycopg.connect(_psycopg_url(empty_database)) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        tables = connection.execute(
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename LIKE 'api_list_snapshot%'"
        ).fetchall()

    assert revision == ("0002",)
    assert {row[0] for row in tables} == {"api_list_snapshots", "api_list_snapshot_items"}


def test_seeded_upgrade_preserves_metrics_and_backfills_attempts(seeded_database: str) -> None:
    with psycopg.connect(_psycopg_url(seeded_database)) as connection:
        rows = connection.execute(
            "SELECT post_id, status::text, x_pv_count, landing_user_count, "
            "measured_at IS NOT NULL, attempt_count, memory_attempt_count "
            "FROM post_metrics ORDER BY post_id"
        ).fetchall()

    assert rows == [
        (101, "pending", None, None, False, 0, 0),
        (102, "completed", 20, 4, True, 0, 0),
        (103, "failed", 8, None, False, 0, 0),
    ]


def test_catalog_has_expected_constraints_indexes_and_fk_actions(seeded_database: str) -> None:
    with psycopg.connect(_psycopg_url(seeded_database)) as connection:
        indexes = dict(
            connection.execute(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename IN "
                "('post_metrics', 'api_list_snapshots')"
            ).fetchall()
        )
        constraints = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT c.conname, pg_get_constraintdef(c.oid), c.confdeltype "
                "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                "WHERE t.relname IN "
                "('post_metrics', 'api_list_snapshots', 'api_list_snapshot_items')"
            ).fetchall()
        }
        counters = connection.execute(
            "SELECT column_name, is_nullable, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'post_metrics' "
            "AND column_name IN ('attempt_count', 'memory_attempt_count')"
        ).fetchall()

    assert (
        "(status, next_attempt_at, scheduled_at)"
        in indexes["ix_post_metrics_status_next_scheduled"]
    )
    assert (
        "(memory_generated_at, memory_failed_at, memory_next_attempt_at)"
        in indexes["ix_post_metrics_memory_retry"]
    )
    assert (
        "(marketer_id, resource, expires_at)"
        in indexes["ix_api_list_snapshots_owner_resource_expiry"]
    )
    assert "(expires_at)" in indexes["ix_api_list_snapshots_expiry"]
    assert "attempt_count >= 0" in constraints["ck_post_metrics_attempts_non_negative"][0]
    assert "resource" in constraints["ck_api_list_snapshots_resource"][0]
    position_check = constraints["ck_api_list_snapshot_items_position"][0].replace('"', "")
    assert "position >= 0" in position_check
    item_primary_key = constraints["api_list_snapshot_items_pkey"][0]
    assert item_primary_key.startswith("PRIMARY KEY")
    assert "snapshot_id" in item_primary_key and "position" in item_primary_key
    assert constraints["post_metrics_post_id_fkey"][1] == "r"
    assert constraints["api_list_snapshots_marketer_id_fkey"][1] == "c"
    assert constraints["api_list_snapshot_items_snapshot_id_fkey"][1] == "c"
    assert {row[0] for row in counters} == {"attempt_count", "memory_attempt_count"}
    assert all(nullable == "NO" and default.startswith("0") for _, nullable, default in counters)


def test_snapshot_delete_cascades_items(seeded_database: str) -> None:
    snapshot_id = uuid.uuid4()
    with psycopg.connect(_psycopg_url(seeded_database)) as connection:
        connection.execute(
            "INSERT INTO api_list_snapshots "
            "(id, marketer_id, resource, filter_hash, expires_at) "
            "VALUES (%s, 101, 'posts', %s, now() + interval '30 minutes')",
            (snapshot_id, "d" * 64),
        )
        connection.execute(
            "INSERT INTO api_list_snapshot_items (snapshot_id, position, item) "
            "VALUES (%s, 0, '{\"id\": 101}'::jsonb)",
            (snapshot_id,),
        )
        connection.execute("DELETE FROM api_list_snapshots WHERE id = %s", (snapshot_id,))
        count = connection.execute(
            "SELECT count(*) FROM api_list_snapshot_items WHERE snapshot_id = %s", (snapshot_id,)
        ).fetchone()

    assert count == (0,)


@pytest.mark.parametrize(
    ("statement", "parameters"),
    [
        ("UPDATE post_metrics SET x_pv_count = -1 WHERE post_id = 101", None),
        ("UPDATE post_metrics SET landing_user_count = -1 WHERE post_id = 101", None),
        ("UPDATE post_metrics SET attempt_count = -1 WHERE post_id = 101", None),
        ("UPDATE post_metrics SET memory_attempt_count = -1 WHERE post_id = 101", None),
        (
            "INSERT INTO api_list_snapshots "
            "(id, marketer_id, resource, filter_hash, expires_at) "
            "VALUES (%s, 101, 'campaigns', %s, now())",
            (uuid.uuid4(), "e" * 64),
        ),
        (
            "WITH snapshot AS ("
            "INSERT INTO api_list_snapshots "
            "(id, marketer_id, resource, filter_hash, expires_at) "
            "VALUES (%s, 101, 'posts', %s, now()) RETURNING id"
            ") INSERT INTO api_list_snapshot_items (snapshot_id, position, item) "
            "SELECT id, -1, '{}'::jsonb FROM snapshot",
            (uuid.uuid4(), "f" * 64),
        ),
    ],
)
def test_catalog_constraints_reject_invalid_values(
    seeded_database: str, statement: str, parameters: tuple[object, ...] | None
) -> None:
    with (
        psycopg.connect(_psycopg_url(seeded_database)) as connection,
        pytest.raises(errors.CheckViolation),
    ):
        connection.execute(sql.SQL(cast(LiteralString, statement)), parameters)


def test_alembic_has_no_schema_drift(empty_database: str) -> None:
    _alembic(empty_database, "check")


def test_downgrade_preserves_core_metrics_and_drops_additive_state() -> None:
    with _temporary_database() as database_url:
        _alembic(database_url, "upgrade", "0001")
        _seed_0001(database_url)
        _alembic(database_url, "upgrade", "head")
        _alembic(database_url, "downgrade", "0001")

        with psycopg.connect(_psycopg_url(database_url)) as connection:
            metrics = connection.execute(
                "SELECT post_id, status::text, x_pv_count, landing_user_count "
                "FROM post_metrics ORDER BY post_id"
            ).fetchall()
            columns = connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'post_metrics'"
            ).fetchall()
            snapshots = connection.execute("SELECT to_regclass('api_list_snapshots')").fetchone()

    assert metrics == [
        (101, "pending", None, None),
        (102, "completed", 20, 4),
        (103, "failed", 8, None),
    ]
    assert "attempt_count" not in {row[0] for row in columns}
    assert snapshots == (None,)
