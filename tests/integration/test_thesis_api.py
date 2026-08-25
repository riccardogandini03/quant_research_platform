"""End-to-end coverage for the versioned thesis lifecycle API."""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from apps.api import main as api_main
from quant_raas.config import Settings

pytestmark = pytest.mark.integration

SECURITY_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_SECURITY_ID = UUID("22222222-2222-4222-8222-222222222222")
MISSING_SECURITY_ID = UUID("33333333-3333-4333-8333-333333333333")

CONTENT: dict[str, Any] = {
    "summary": "Relative strength supports the case.",
    "drivers": [
        {
            "node_id": "relative_strength",
            "statement": "Relative performance remains resilient.",
            "supporting_features": ["relative_return_sector_63d"],
            "direction": "positive",
        }
    ],
}


def _security_payload(security_id: UUID, *, name: str) -> dict[str, Any]:
    return {
        "security_id": str(security_id),
        "name": name,
        "primary_currency": "USD",
        "exchange_mic": "XNAS",
        "identifiers": [
            {
                "scheme": "vendor",
                "value": f"{name} US",
                "provider": "test",
                "exchange_mic": "XNAS",
                "valid_from": "2020-01-01T00:00:00Z",
                "is_primary": True,
            }
        ],
    }


def _create_payload(
    *,
    thesis_key: str = "example_core",
    security_id: UUID = SECURITY_ID,
    valid_from: str = "2024-01-09T21:00:00Z",
) -> dict[str, Any]:
    return {
        "thesis_key": thesis_key,
        "security_id": str(security_id),
        "title": "Example core thesis",
        "content": deepcopy(CONTENT),
        "created_by": "analyst@example.com",
        "authored_by": "analyst@example.com",
        "approved_by": "pm@example.com",
        "valid_from": valid_from,
    }


def _append_payload(
    *, expected_version: int, valid_from: str = "2025-01-09T21:00:00Z"
) -> dict[str, Any]:
    content = deepcopy(CONTENT)
    content["summary"] = f"Version after {valid_from}."
    return {
        "content": content,
        "authored_by": "analyst@example.com",
        "approved_by": "pm@example.com",
        "expected_version": expected_version,
        "valid_from": valid_from,
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    settings = Settings(
        environment="test",
        database_url="sqlite+pysqlite:///:memory:",
        database_echo=False,
    )
    monkeypatch.setattr(api_main, "get_settings", lambda: settings)

    with TestClient(api_main.app) as test_client:
        registered = test_client.post(
            "/v1/securities",
            json=_security_payload(SECURITY_ID, name="Example Corp"),
        )
        assert registered.status_code == 201
        yield test_client


def _create_thesis(client: TestClient, **overrides: Any) -> dict[str, Any]:
    payload = _create_payload(**overrides)
    response = client.post("/v1/theses", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["attribution_authenticated"] is False
    return body


def test_thesis_lifecycle_routes_are_point_in_time_and_transactional(
    client: TestClient,
) -> None:
    created = _create_thesis(client)
    assert created["thesis"]["thesis_key"] == "example_core"
    assert created["version"]["version"] == 1
    assert created["version"]["content"] == {
        "schema_version": 1,
        **CONTENT,
        "risks": [],
        "invalidation_rules": [],
    }
    assert created["version"]["created_at"] == created["version"]["approved_at"]

    duplicate = client.post("/v1/theses", json=_create_payload())
    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]

    registered = client.post(
        "/v1/securities",
        json=_security_payload(OTHER_SECURITY_ID, name="Other Corp"),
    )
    assert registered.status_code == 201
    _create_thesis(
        client,
        thesis_key="other_core",
        security_id=OTHER_SECURITY_ID,
    )

    listed = client.get("/v1/theses", params={"security_id": str(SECURITY_ID)})
    assert listed.status_code == 200
    listed_body = listed.json()
    assert [item["thesis_key"] for item in listed_body["items"]] == ["example_core"]
    assert listed_body["attribution_authenticated"] is False
    assert datetime.fromisoformat(listed_body["data_cutoff_at"]).tzinfo is UTC

    detail = client.get(
        "/v1/theses/example_core",
        params={
            "effective_at": "2099-01-10T21:00:00Z",
            "knowledge_time": "2099-01-10T21:00:00Z",
        },
    )
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["selected_version"]["version"] == 1
    assert detail_body["selection_status"] == "selected"
    expected_cutoff = datetime(2099, 1, 10, 21, 0, tzinfo=UTC)
    assert datetime.fromisoformat(detail_body["effective_at"]) == expected_cutoff
    assert datetime.fromisoformat(detail_body["knowledge_time"]) == expected_cutoff
    assert datetime.fromisoformat(detail_body["max_available_at"]) == datetime.fromisoformat(
        created["version"]["approved_at"]
    )
    assert detail_body["attribution_authenticated"] is False

    default_detail = client.get("/v1/theses/example_core")
    assert default_detail.status_code == 200
    assert default_detail.json()["effective_at"] == default_detail.json()["knowledge_time"]

    _create_thesis(
        client,
        thesis_key="future_core",
        valid_from="2100-01-10T21:00:00Z",
    )
    not_effective = client.get(
        "/v1/theses/future_core",
        params={
            "effective_at": "2099-01-10T21:00:00Z",
            "knowledge_time": "2099-01-10T21:00:00Z",
        },
    )
    assert not_effective.status_code == 200
    assert not_effective.json()["selected_version"] is None
    assert not_effective.json()["selection_status"] == "not_yet_effective"
    assert not_effective.json()["max_available_at"] is None

    appended = client.post(
        "/v1/theses/example_core/versions",
        json=_append_payload(expected_version=1),
    )
    assert appended.status_code == 201
    appended_body = appended.json()
    assert appended_body["version"]["version"] == 2
    assert appended_body["attribution_authenticated"] is False

    stale = client.post(
        "/v1/theses/example_core/versions",
        json=_append_payload(expected_version=1, valid_from="2026-01-09T21:00:00Z"),
    )
    assert stale.status_code == 409
    assert "expected version 1" in stale.json()["detail"]

    history = client.get("/v1/theses/example_core/versions")
    assert history.status_code == 200
    history_body = history.json()
    assert [version["version"] for version in history_body["versions"]] == [1, 2]
    assert history_body["thesis"]["thesis_key"] == "example_core"
    assert datetime.fromisoformat(history_body["max_available_at"]) == datetime.fromisoformat(
        appended_body["version"]["approved_at"]
    )
    assert history_body["attribution_authenticated"] is False

    archived = client.request(
        "DELETE",
        "/v1/theses/example_core",
        json={"archived_by": "first@example.com"},
    )
    assert archived.status_code == 200
    archived_body = archived.json()
    assert archived_body["thesis"]["status"] == "archived"
    assert archived_body["thesis"]["archived_by"] == "first@example.com"
    assert archived_body["attribution_authenticated"] is False

    repeated = client.request(
        "DELETE",
        "/v1/theses/example_core",
        json={"archived_by": "second@example.com"},
    )
    assert repeated.status_code == 200
    assert repeated.json() == archived_body

    active_only = client.get("/v1/theses", params={"security_id": str(SECURITY_ID)})
    assert active_only.status_code == 200
    assert [item["thesis_key"] for item in active_only.json()["items"]] == ["future_core"]

    including_archived = client.get(
        "/v1/theses",
        params={"security_id": str(SECURITY_ID), "include_archived": True},
    )
    assert including_archived.status_code == 200
    assert [item["thesis_key"] for item in including_archived.json()["items"]] == [
        "example_core",
        "future_core",
    ]

    after_archive = client.post(
        "/v1/theses/example_core/versions",
        json=_append_payload(expected_version=2, valid_from="2026-01-09T21:00:00Z"),
    )
    assert after_archive.status_code == 409
    assert "archived" in after_archive.json()["detail"]

    unchanged_history = client.get("/v1/theses/example_core/versions")
    assert unchanged_history.status_code == 200
    assert [item["version"] for item in unchanged_history.json()["versions"]] == [1, 2]


def test_unknown_key_and_missing_security_use_typed_http_statuses(
    client: TestClient,
) -> None:
    unknown = client.get("/v1/theses/missing_core/versions")
    assert unknown.status_code == 404
    assert "missing_core" in unknown.json()["detail"]

    missing_reference = client.post(
        "/v1/theses",
        json=_create_payload(
            thesis_key="missing_security_core",
            security_id=MISSING_SECURITY_ID,
        ),
    )
    assert missing_reference.status_code == 422
    assert "security" in missing_reference.json()["detail"]

    empty = client.get(
        "/v1/theses",
        params={"security_id": str(MISSING_SECURITY_ID), "include_archived": True},
    )
    assert empty.status_code == 200
    assert empty.json()["items"] == []


@pytest.mark.parametrize(
    ("change", "expected_location"),
    [
        ({"thesis_key": "Bad Key"}, "thesis_key"),
        ({"content": {"summary": ""}}, "summary"),
        (
            {
                "content": {
                    "summary": "Invalid thresholds.",
                    "invalidation_rules": [
                        {
                            "node_id": "revenue_break",
                            "statement": "Growth breaches the floor.",
                            "feature_name": "revenue_growth_yoy",
                            "comparator": "greater_than_or_equal",
                            "warning_threshold": 10.0,
                            "breach_threshold": 5.0,
                        }
                    ],
                }
            },
            "invalidation_rules",
        ),
        ({"created_at": "2024-01-01T00:00:00Z"}, "created_at"),
        ({"approved_at": "2024-01-01T00:00:00Z"}, "approved_at"),
        ({"valid_from": "2024-01-09T21:00:00"}, "valid_from"),
    ],
)
def test_create_rejects_malformed_domain_and_client_owned_fields(
    client: TestClient,
    change: dict[str, Any],
    expected_location: str,
) -> None:
    payload = _create_payload()
    payload.update(deepcopy(change))

    response = client.post("/v1/theses", json=payload)

    assert response.status_code == 422
    assert expected_location in str(response.json()["detail"])


@pytest.mark.parametrize("field", ["created_at", "approved_at"])
def test_append_rejects_client_owned_audit_timestamps(
    client: TestClient,
    field: str,
) -> None:
    _create_thesis(client)
    payload = _append_payload(expected_version=1)
    payload[field] = "2024-01-01T00:00:00Z"

    response = client.post("/v1/theses/example_core/versions", json=payload)

    assert response.status_code == 422
    history = client.get("/v1/theses/example_core/versions")
    assert history.status_code == 200
    assert [item["version"] for item in history.json()["versions"]] == [1]


def test_append_rejects_naive_valid_from(client: TestClient) -> None:
    _create_thesis(client)
    payload = _append_payload(expected_version=1, valid_from="2025-01-09T21:00:00")

    response = client.post("/v1/theses/example_core/versions", json=payload)

    assert response.status_code == 422


@pytest.mark.parametrize("query_name", ["effective_at", "knowledge_time"])
def test_detail_rejects_naive_cutoffs_before_service_entry(
    client: TestClient,
    query_name: str,
) -> None:
    response = client.get(
        "/v1/theses/missing_core",
        params={query_name: "2024-01-09T21:00:00"},
    )

    assert response.status_code == 422
    assert query_name in str(response.json()["detail"])


def test_list_requires_security_id(client: TestClient) -> None:
    response = client.get("/v1/theses")

    assert response.status_code == 422
    assert "security_id" in str(response.json()["detail"])


@pytest.mark.parametrize("field", ["title", "created_by", "authored_by", "approved_by"])
def test_create_rejects_whitespace_only_direct_strings(
    client: TestClient,
    field: str,
) -> None:
    payload = _create_payload()
    payload[field] = "   "

    response = client.post("/v1/theses", json=payload)

    assert response.status_code == 422
    assert field in str(response.json()["detail"])


@pytest.mark.parametrize("field", ["authored_by", "approved_by"])
def test_append_rejects_whitespace_only_attribution_before_service_entry(
    client: TestClient,
    field: str,
) -> None:
    payload = _append_payload(expected_version=1)
    payload[field] = "   "

    response = client.post("/v1/theses/missing_core/versions", json=payload)

    assert response.status_code == 422
    assert field in str(response.json()["detail"])


def test_archive_rejects_whitespace_only_attribution_before_service_entry(
    client: TestClient,
) -> None:
    response = client.request(
        "DELETE",
        "/v1/theses/missing_core",
        json={"archived_by": "   "},
    )

    assert response.status_code == 422
    assert "archived_by" in str(response.json()["detail"])


def test_direct_request_strings_strip_surrounding_whitespace_consistently(
    client: TestClient,
) -> None:
    create_payload = _create_payload(thesis_key="spaced_core")
    create_payload.update(
        {
            "thesis_key": "  spaced_core  ",
            "title": "  Spaced title  ",
            "created_by": "  creator@example.com  ",
            "authored_by": "  author@example.com  ",
            "approved_by": "  approver@example.com  ",
        }
    )

    created = client.post("/v1/theses", json=create_payload)

    assert created.status_code == 201
    assert created.json()["thesis"]["thesis_key"] == "spaced_core"
    assert created.json()["thesis"]["title"] == "Spaced title"
    assert created.json()["thesis"]["created_by"] == "creator@example.com"
    assert created.json()["version"]["authored_by"] == "author@example.com"
    assert created.json()["version"]["approved_by"] == "approver@example.com"

    append_payload = _append_payload(expected_version=1)
    append_payload["authored_by"] = "  next-author@example.com  "
    append_payload["approved_by"] = "  next-approver@example.com  "
    appended = client.post("/v1/theses/spaced_core/versions", json=append_payload)
    assert appended.status_code == 201
    assert appended.json()["version"]["authored_by"] == "next-author@example.com"
    assert appended.json()["version"]["approved_by"] == "next-approver@example.com"

    archived = client.request(
        "DELETE",
        "/v1/theses/spaced_core",
        json={"archived_by": "  archiver@example.com  "},
    )
    assert archived.status_code == 200
    assert archived.json()["thesis"]["archived_by"] == "archiver@example.com"
