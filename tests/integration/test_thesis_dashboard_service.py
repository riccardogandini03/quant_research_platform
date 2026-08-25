"""Dashboard-form content through the real thesis service boundary."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from apps.dashboard.thesis_panel import content_from_editor_rows
from quant_raas.domain.security import Security
from quant_raas.runtime import repositories_for
from quant_raas.services.theses import ThesisService


def _stored_nodes_json(session: Session, thesis_version_id) -> str:
    value = (
        session.connection()
        .exec_driver_sql(
            "SELECT nodes FROM thesis_version WHERE thesis_version_id = ?",
            (thesis_version_id.hex,),
        )
        .scalar_one()
    )
    assert isinstance(value, str)
    return value


def test_dashboard_rows_create_append_and_archive_immutable_thesis_history(
    sqlite_session: Session,
    sample_security: Security,
    fixed_now: datetime,
) -> None:
    original_content = content_from_editor_rows(
        summary="Demand durability supports the long-term case.",
        driver_rows=[
            {
                "node_id": "relative_strength",
                "statement": "Relative strength remains positive.",
                "supporting_features": "relative_return_sector_63d",
                "direction": "positive",
            }
        ],
        risk_rows=[],
        invalidation_rows=[],
    )
    edited_content = content_from_editor_rows(
        summary="Demand durability and momentum support the long-term case.",
        driver_rows=[
            {
                "node_id": "relative_strength",
                "statement": "Relative strength remains positive.",
                "supporting_features": "relative_return_sector_63d, beta_126d",
                "direction": "positive",
            }
        ],
        risk_rows=[],
        invalidation_rows=[],
    )
    service = ThesisService(
        repositories_for(sqlite_session).securities,
        repositories_for(sqlite_session).theses,
        clock=lambda: fixed_now,
    )

    with sqlite_session.begin():
        repositories_for(sqlite_session).securities.add_security(sample_security)
        created = service.create(
            thesis_key="example_core",
            security_id=sample_security.security_id,
            title="Example core thesis",
            content=original_content,
            created_by="pm@example.com",
            authored_by="analyst@example.com",
            approved_by="pm@example.com",
            valid_from=fixed_now - timedelta(days=1),
        )
        original_nodes_json = _stored_nodes_json(sqlite_session, created.version.thesis_version_id)

    with sqlite_session.begin():
        appended = service.append_version(
            "example_core",
            content=edited_content,
            authored_by="analyst@example.com",
            approved_by="pm@example.com",
            expected_version=1,
            valid_from=fixed_now,
        )

    with sqlite_session.begin():
        archived = service.archive("example_core", archived_by="pm@example.com")
        history = service.history("example_core")
        archived_original_json = _stored_nodes_json(
            sqlite_session, created.version.thesis_version_id
        )

    assert tuple(version.version for version in history) == (1, 2)
    assert history[0].content == original_content
    assert history[1].content == edited_content
    assert appended.version == 2
    assert archived.archived_at == fixed_now
    assert original_nodes_json == archived_original_json
