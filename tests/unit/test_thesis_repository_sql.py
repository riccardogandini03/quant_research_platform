"""SQL-shape checks for thesis repository concurrency primitives."""

from uuid import UUID

from sqlalchemy.dialects import postgresql

from quant_raas.storage.repositories import _locked_thesis_statement

THESIS_ID = UUID("71717171-7171-4717-8717-717171717171")


def test_thesis_identity_lock_compiles_to_postgresql_for_update() -> None:
    statement = _locked_thesis_statement(THESIS_ID)

    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE" in compiled
    assert "thesis.thesis_id" in compiled
    assert statement.get_execution_options()["populate_existing"] is True
