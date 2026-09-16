"""Baseline schema.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-09-15

-----------------------------------------------------------------------------
NOTE ON HOW THIS MIGRATION CREATES TABLES
-----------------------------------------------------------------------------
Table creation goes through `Base.metadata.create_all()` rather than ~34
hand-written `op.create_table()` calls.

Why: this is the initial revision, authored before the toolchain was available
to run `alembic revision --autogenerate`. A hand-transcribed baseline of this
size cannot be verified against the models without running it, and a single
mistyped column type produces a schema that drifts from the ORM silently.
Generating from metadata is correct by construction on a fresh database.

The known limitation: `create_all` reads the metadata as it exists WHEN THE
MIGRATION RUNS, not as it existed when the migration was written. Once a
delta migration (0002+) is added, a fresh `alembic upgrade head` would create
the newest schema at 0001 and then fail applying 0002.

Remediation, to be done on the first environment with a working toolchain and
BEFORE any delta migration is authored - see docs/OPEN_ITEMS.md #8:

    alembic upgrade head            # against an empty database
    alembic revision --autogenerate -m "baseline"   # capture explicit DDL
    # replace the body of this file with the generated op.create_table calls,
    # keeping the raw DDL sections below

CI runs `alembic upgrade head` followed by `alembic check`, so any divergence
between the ORM metadata and the migrated schema fails the build.
-----------------------------------------------------------------------------
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.models import APPEND_ONLY_TABLES, Base

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Append-only enforcement
# ---------------------------------------------------------------------------
# The audit trail must not be rewritable by the application. Enforcing this in
# Python only would mean the guarantee holds exactly as long as every future
# code path remembers it. A trigger makes it structural.
#
# Intentionally not bypassable by the application role. A genuine correction is
# a new row, never an edit; a genuine purge runs as the retention job under a
# separate role that may set `caready.allow_append_only_purge`.
# ---------------------------------------------------------------------------

APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION caready_reject_mutation() RETURNS trigger AS $$
BEGIN
    IF current_setting('caready.allow_append_only_purge', true) = 'on'
       AND TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION
        'Table % is append-only; % is not permitted', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    bind = op.get_bind()

    # gen_random_uuid() is built into PostgreSQL 13+. pgcrypto is created
    # anyway so the schema also applies to a 12.x instance without edits.
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    # Trigram index support for the catalog fuzzy matcher (§6.1).
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')

    Base.metadata.create_all(bind=bind)

    # -- append-only triggers -------------------------------------------------
    op.execute(APPEND_ONLY_FUNCTION)
    for table in APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION caready_reject_mutation();
            """
        )

    # -- indexes metadata cannot express -------------------------------------
    # Trigram indexes for the catalog matcher. Without these, fuzzy lookup
    # against the alias table degrades to a sequential scan as the catalog
    # grows.
    op.execute(
        "CREATE INDEX ix_variant_aliases_raw_key_trgm "
        "ON variant_aliases USING gin (raw_key gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_variants_normalized_trim_trgm "
        "ON variants USING gin (normalized_trim gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_vehicle_models_normalized_name_trgm "
        "ON vehicle_models USING gin (normalized_name gin_trgm_ops)"
    )

    # Partial indexes for the work queues. These are read on every dashboard
    # load and are almost entirely empty rows-of-interest against a large
    # table, which is exactly what a partial index is for.
    op.execute(
        "CREATE INDEX ix_cross_check_open_blockers ON cross_check_results (unit_id) "
        "WHERE resolved_at IS NULL AND severity = 'BLOCKER'"
    )
    op.execute(
        "CREATE INDEX ix_verification_queue_open ON verification_queue (priority, created_at) "
        "WHERE resolved_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_variant_resolution_queue_open ON variant_resolution_queue (created_at) "
        "WHERE resolved_at IS NULL"
    )
    op.execute(
        "CREATE INDEX ix_damage_corrections_unexported ON damage_corrections (created_at) "
        "WHERE exported_at IS NULL"
    )
    # Exactly one active price result and one active grade per unit.
    op.execute(
        "CREATE UNIQUE INDEX uq_price_results_active ON price_results (unit_id) "
        "WHERE superseded_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_grades_active_per_source ON grades (unit_id, source) "
        "WHERE superseded_at IS NULL"
    )

    # -- CHECK constraints requiring cross-column logic -----------------------
    # A flagged checklist item without a note is not actionable; the service
    # layer produces the friendly error, this makes it impossible to bypass.
    op.create_check_constraint(
        "flagged_requires_note",
        "non_visual_checklist_items",
        "answer <> 'flagged' OR (note IS NOT NULL AND length(trim(note)) > 0)",
    )
    # An override without a reason is not auditable (§7.4, §8.6).
    op.create_check_constraint(
        "override_requires_reason",
        "grades",
        "overrides_grade_id IS NULL OR (override_reason IS NOT NULL AND length(trim(override_reason)) > 0)",
    )
    op.create_check_constraint(
        "price_override_requires_reason",
        "price_results",
        "override_base_price_idr IS NULL "
        "OR (override_reason IS NOT NULL AND length(trim(override_reason)) > 0)",
    )
    # Deduction must reconcile: amp - base_price. Guards against a code path
    # writing a deduction from a table instead of from the two predictions.
    op.create_check_constraint(
        "deduction_reconciles",
        "price_results",
        "abs(deduction_idr - (amp_idr - base_price_idr)) < 1",
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in APPEND_ONLY_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS caready_reject_mutation()")
    Base.metadata.drop_all(bind=bind)
