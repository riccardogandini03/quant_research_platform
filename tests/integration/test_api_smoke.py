"""Small TestClient smoke tests with an isolated in-memory SQLite database."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.api import main as api_main
from apps.api.schemas import DailyRunRequest
from quant_raas.config import Settings

pytestmark = pytest.mark.integration


def test_health_and_coverage_validation_are_network_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        database_echo=False,
    )
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)

    with TestClient(api_main.app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "database": "available"}

        # This request exercises multipart parsing and the real CSV contract;
        # it never resolves a vendor identifier or leaves the local process.
        validation = client.post(
            "/v1/coverage/validate",
            files={
                "file": (
                    "coverage.csv",
                    b"identifier,peer_group\nEXAMPLE US,enterprise_software\n",
                    "text/csv",
                )
            },
        )
        assert validation.status_code == 200
        payload = validation.json()
        assert payload["valid"] is True
        assert payload["rows"][0]["identifier"] == "EXAMPLE US"
        assert payload["rows"][0]["peer_group"] == "enterprise_software"

        # A request-scoped session runs on the TestClient worker thread. The
        # shared in-memory engine must expose the schema created at lifespan.
        securities = client.get("/v1/securities")
        assert securities.status_code == 200
        assert securities.json() == []


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), float("-inf")])
def test_daily_run_schema_rejects_non_finite_position_weights(weight: float) -> None:
    with pytest.raises(ValidationError, match="position weights must be finite"):
        DailyRunRequest(
            coverage_list_id=UUID(int=1),
            as_of=datetime(2024, 1, 9, 21, 0, tzinfo=UTC),
            data_cutoff_at=datetime(2024, 1, 9, 21, 5, tzinfo=UTC),
            position_weights={UUID(int=2): weight},
        )
