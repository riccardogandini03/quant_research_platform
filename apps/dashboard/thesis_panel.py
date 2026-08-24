"""Structured thesis authoring and immutable history for the company dashboard."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from quant_raas.common.errors import ThesisConflictError, ThesisReferenceError
from quant_raas.domain.enums import InvalidationComparator, ThesisDirection, ThesisRiskSeverity
from quant_raas.domain.research import (
    ThesisContent,
    ThesisDriver,
    ThesisInvalidationRule,
    ThesisRisk,
    ThesisVersion,
)
from quant_raas.runtime import repositories_for
from quant_raas.services.theses import ThesisService

_DRIVER_COLUMNS = ("node_id", "statement", "supporting_features", "direction")
_RISK_COLUMNS = ("node_id", "statement", "watch_features", "severity")
_INVALIDATION_COLUMNS = (
    "node_id",
    "statement",
    "feature_name",
    "comparator",
    "warning_threshold",
    "breach_threshold",
    "unit",
)
_EMPTY_DRIVER_ROW: Mapping[str, object] = {
    "node_id": "",
    "statement": "",
    "supporting_features": "",
    "direction": ThesisDirection.POSITIVE.value,
}
_EMPTY_RISK_ROW: Mapping[str, object] = {
    "node_id": "",
    "statement": "",
    "watch_features": "",
    "severity": ThesisRiskSeverity.MEDIUM.value,
}
_EMPTY_INVALIDATION_ROW: Mapping[str, object] = {
    "node_id": "",
    "statement": "",
    "feature_name": "",
    "comparator": InvalidationComparator.GREATER_THAN_OR_EQUAL.value,
    "warning_threshold": 0.0,
    "breach_threshold": 0.0,
    "unit": "",
}


@dataclass(frozen=True, slots=True)
class ThesisEditorRows:
    drivers: list[dict[str, object]]
    risks: list[dict[str, object]]
    invalidation_rules: list[dict[str, object]]


def _features(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part.strip().lower() for part in str(value).split(",") if part.strip())


def _is_untouched_row(row: Mapping[str, object], template: Mapping[str, object]) -> bool:
    return dict(row) == dict(template)


def content_from_editor_rows(
    *,
    summary: str,
    driver_rows: Sequence[Mapping[str, object]],
    risk_rows: Sequence[Mapping[str, object]],
    invalidation_rows: Sequence[Mapping[str, object]],
) -> ThesisContent:
    """Build the strict thesis contract from the dashboard's editable table rows."""

    return ThesisContent(
        summary=summary,
        drivers=tuple(
            ThesisDriver(
                node_id=str(row.get("node_id", "")),
                statement=str(row.get("statement", "")),
                supporting_features=_features(row.get("supporting_features")),
                direction=ThesisDirection(str(row.get("direction", ""))),
            )
            for row in driver_rows
            if not _is_untouched_row(row, _EMPTY_DRIVER_ROW)
        ),
        risks=tuple(
            ThesisRisk(
                node_id=str(row.get("node_id", "")),
                statement=str(row.get("statement", "")),
                watch_features=_features(row.get("watch_features")),
                severity=ThesisRiskSeverity(str(row.get("severity", ""))),
            )
            for row in risk_rows
            if not _is_untouched_row(row, _EMPTY_RISK_ROW)
        ),
        invalidation_rules=tuple(
            ThesisInvalidationRule(
                node_id=str(row.get("node_id", "")),
                statement=str(row.get("statement", "")),
                feature_name=str(row.get("feature_name", "")),
                comparator=InvalidationComparator(str(row.get("comparator", ""))),
                warning_threshold=float(row.get("warning_threshold", "")),
                breach_threshold=float(row.get("breach_threshold", "")),
                unit=str(row["unit"]) if row.get("unit") else None,
            )
            for row in invalidation_rows
            if not _is_untouched_row(row, _EMPTY_INVALIDATION_ROW)
        ),
    )


def editor_rows_from_content(content: ThesisContent) -> ThesisEditorRows:
    """Turn a typed thesis version into the exact editable dashboard row shape."""

    return ThesisEditorRows(
        drivers=[
            {
                "node_id": driver.node_id,
                "statement": driver.statement,
                "supporting_features": ", ".join(driver.supporting_features),
                "direction": driver.direction.value,
            }
            for driver in content.drivers
        ],
        risks=[
            {
                "node_id": risk.node_id,
                "statement": risk.statement,
                "watch_features": ", ".join(risk.watch_features),
                "severity": risk.severity.value,
            }
            for risk in content.risks
        ],
        invalidation_rules=[
            {
                "node_id": rule.node_id,
                "statement": rule.statement,
                "feature_name": rule.feature_name,
                "comparator": rule.comparator.value,
                "warning_threshold": rule.warning_threshold,
                "breach_threshold": rule.breach_threshold,
                "unit": rule.unit or "",
            }
            for rule in content.invalidation_rules
        ],
    )


def parse_utc_timestamp(value: str) -> datetime:
    """Parse an explicitly offset ISO-8601 timestamp and normalize it to UTC."""

    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as error:
        raise ValueError("valid_from must be a valid ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("valid_from must include a UTC offset (Z or ±HH:MM)")
    return parsed.astimezone(UTC)


def _empty_rows(template: Mapping[str, object]) -> list[dict[str, object]]:
    return [dict(template)]


def _records(editor_value: Any) -> list[dict[str, object]]:
    """Accept Streamlit's dataframe-shaped editor response without leaking pandas outward."""

    if hasattr(editor_value, "to_dict"):
        return list(editor_value.to_dict(orient="records"))
    return [dict(row) for row in editor_value]


def _version_label(version: ThesisVersion) -> str:
    return f"v{version.version} · effective {version.valid_from.isoformat()}"


def _node_rows(content: ThesisContent) -> list[dict[str, object]]:
    return (
        [
            {
                "kind": "driver",
                "node_id": node.node_id,
                "statement": node.statement,
                "supporting_features": ", ".join(node.supporting_features),
                "direction": node.direction.value,
            }
            for node in content.drivers
        ]
        + [
            {
                "kind": "risk",
                "node_id": node.node_id,
                "statement": node.statement,
                "watch_features": ", ".join(node.watch_features),
                "severity": node.severity.value,
            }
            for node in content.risks
        ]
        + [
            {
                "kind": "invalidation",
                "node_id": node.node_id,
                "statement": node.statement,
                "feature_name": node.feature_name,
                "comparator": node.comparator.value,
                "warning_threshold": node.warning_threshold,
                "breach_threshold": node.breach_threshold,
                "unit": node.unit,
                "invalidation_state": "not evaluated",
            }
            for node in content.invalidation_rules
        ]
    )


def _version_history_rows(history: Sequence[ThesisVersion]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for version in history:
        version_fields: dict[str, object] = {
            "version": version.version,
            "valid_from": version.valid_from,
            "approved_at": version.approved_at,
            "authored_by": version.authored_by,
            "approved_by": version.approved_by,
            "summary": version.content.summary,
        }
        nodes = _node_rows(version.content)
        if nodes:
            rows.extend({**version_fields, **node} for node in nodes)
        else:
            rows.append({**version_fields, "kind": "none"})
    return rows


def _render_history(thesis, history: tuple[ThesisVersion, ...]) -> ThesisVersion:
    st.subheader("Thesis history")
    st.caption(
        f"{thesis.thesis_key} · {thesis.status.value} · {thesis.title} · created by "
        f"{thesis.created_by} at {thesis.created_at.isoformat()}"
    )
    versions = {version.version: version for version in history}
    selected_number = st.selectbox(
        "Selected version",
        options=list(versions),
        index=len(versions) - 1,
        format_func=lambda value: _version_label(versions[value]),
        key=f"thesis-version-{thesis.thesis_id}",
    )
    selected_version = versions[selected_number]
    st.markdown(selected_version.content.summary)
    st.caption(
        f"Authored by {selected_version.authored_by}; approved by "
        f"{selected_version.approved_by} at {selected_version.approved_at.isoformat()}; "
        f"effective from {selected_version.valid_from.isoformat()}"
    )
    st.dataframe(
        _node_rows(selected_version.content),
        use_container_width=True,
        hide_index=True,
    )
    st.dataframe(
        _version_history_rows(history),
        use_container_width=True,
        hide_index=True,
    )
    return selected_version


def _render_editor(
    initial: ThesisContent | None, *, key_prefix: str
) -> tuple[str, list, list, list]:
    rows = (
        editor_rows_from_content(initial)
        if initial is not None
        else ThesisEditorRows(drivers=[], risks=[], invalidation_rules=[])
    )
    summary = st.text_area(
        "Summary",
        value=initial.summary if initial is not None else "",
        key=f"{key_prefix}-summary",
    )
    st.caption("Feature names are comma-separated canonical identifiers.")
    drivers = st.data_editor(
        rows.drivers or _empty_rows(_EMPTY_DRIVER_ROW),
        column_order=_DRIVER_COLUMNS,
        num_rows="dynamic",
        key=f"{key_prefix}-drivers",
        use_container_width=True,
    )
    risks = st.data_editor(
        rows.risks or _empty_rows(_EMPTY_RISK_ROW),
        column_order=_RISK_COLUMNS,
        num_rows="dynamic",
        key=f"{key_prefix}-risks",
        use_container_width=True,
    )
    invalidations = st.data_editor(
        rows.invalidation_rules or _empty_rows(_EMPTY_INVALIDATION_ROW),
        column_order=_INVALIDATION_COLUMNS,
        num_rows="dynamic",
        key=f"{key_prefix}-invalidations",
        use_container_width=True,
    )
    return summary, _records(drivers), _records(risks), _records(invalidations)


def _authoring_fields(*, key_prefix: str) -> tuple[str, str, str, bool]:
    valid_from = st.text_input(
        "Valid from (ISO-8601 with Z or offset)",
        value="",
        key=f"{key_prefix}-valid-from",
    )
    authored_by = st.text_input("Authored by", key=f"{key_prefix}-authored-by")
    approved_by = st.text_input("Approved by", key=f"{key_prefix}-approved-by")
    approval_confirmed = st.checkbox(
        "I explicitly approve this version for activation.",
        key=f"{key_prefix}-approval-confirmed",
    )
    return valid_from, authored_by, approved_by, approval_confirmed


def _save_content(
    *,
    session_factory,
    security_id: UUID,
    thesis_key: str,
    title: str | None,
    created_by: str | None,
    summary: str,
    driver_rows: list[dict[str, object]],
    risk_rows: list[dict[str, object]],
    invalidation_rows: list[dict[str, object]],
    valid_from_text: str,
    authored_by: str,
    approved_by: str,
    approval_confirmed: bool,
    expected_version: int | None,
) -> None:
    if not authored_by.strip() or not approved_by.strip():
        st.error("Authored by and approved by are required.")
        return
    if not approval_confirmed:
        st.error("Explicit approval is required before activation.")
        return
    try:
        valid_from = parse_utc_timestamp(valid_from_text)
        content = content_from_editor_rows(
            summary=summary,
            driver_rows=driver_rows,
            risk_rows=risk_rows,
            invalidation_rows=invalidation_rows,
        )
        with session_factory.begin() as session:
            repositories = repositories_for(session)
            service = ThesisService(repositories.securities, repositories.theses)
            if expected_version is None:
                if title is None or created_by is None:
                    raise ValueError("Title and created by are required to create a thesis.")
                service.create(
                    thesis_key=thesis_key,
                    security_id=security_id,
                    title=title,
                    content=content,
                    created_by=created_by,
                    authored_by=authored_by,
                    approved_by=approved_by,
                    valid_from=valid_from,
                )
            else:
                service.append_version(
                    thesis_key,
                    content=content,
                    authored_by=authored_by,
                    approved_by=approved_by,
                    expected_version=expected_version,
                    valid_from=valid_from,
                )
    except (ValidationError, ThesisConflictError, ThesisReferenceError, ValueError) as error:
        st.error(str(error))
        return
    st.rerun()


def render_thesis_panel(session_factory, security_id: UUID) -> None:
    """Render company-scoped thesis reading, authoring, versioning, and archival controls."""

    global st
    import streamlit as st

    st.divider()
    st.header("Investment theses")
    with session_factory() as session:
        repositories = repositories_for(session)
        service = ThesisService(repositories.securities, repositories.theses)
        active = service.list_for_security(security_id)
        identities = service.list_for_security(security_id, include_archived=True)

    active_ids = {thesis.thesis_id for thesis in active}
    if identities:
        thesis_by_key = {thesis.thesis_key: thesis for thesis in identities}
        selected_key = st.selectbox(
            "Thesis identity",
            options=list(thesis_by_key),
            format_func=lambda key: (
                f"{key} · {thesis_by_key[key].status.value} · {thesis_by_key[key].title}"
            ),
        )
        selected_thesis = thesis_by_key[selected_key]
        with session_factory() as session:
            repositories = repositories_for(session)
            history = ThesisService(repositories.securities, repositories.theses).history(
                selected_key
            )
        selected_version = _render_history(selected_thesis, history)
    else:
        selected_thesis = None
        selected_version = None
        st.info("No thesis exists for this security yet. Create one below.")

    action_options = ["Create thesis"]
    if selected_thesis is not None and selected_thesis.thesis_id in active_ids:
        action_options.append("Append selected thesis")
    action = st.radio("Authoring action", action_options, horizontal=True)

    if action == "Create thesis":
        create_prefix = f"create-thesis-{security_id}"
        thesis_key = st.text_input("Thesis key", key=f"{create_prefix}-key")
        title = st.text_input("Title (immutable after creation)", key=f"{create_prefix}-title")
        created_by = st.text_input("Created by", key=f"{create_prefix}-created-by")
        summary, drivers, risks, invalidations = _render_editor(
            None,
            key_prefix=create_prefix,
        )
        valid_from, authored_by, approved_by, approval_confirmed = _authoring_fields(
            key_prefix=create_prefix
        )
        if st.button("Create thesis", key=f"{create_prefix}-submit"):
            _save_content(
                session_factory=session_factory,
                security_id=security_id,
                thesis_key=thesis_key,
                title=title,
                created_by=created_by,
                summary=summary,
                driver_rows=drivers,
                risk_rows=risks,
                invalidation_rows=invalidations,
                valid_from_text=valid_from,
                authored_by=authored_by,
                approved_by=approved_by,
                approval_confirmed=approval_confirmed,
                expected_version=None,
            )
    elif selected_thesis is not None and selected_version is not None:
        append_prefix = f"append-thesis-{selected_thesis.thesis_id}-{selected_version.version}"
        st.caption(f"Appending to immutable title: {selected_thesis.title}")
        summary, drivers, risks, invalidations = _render_editor(
            selected_version.content,
            key_prefix=append_prefix,
        )
        valid_from, authored_by, approved_by, approval_confirmed = _authoring_fields(
            key_prefix=append_prefix
        )
        if st.button("Append version", key=f"{append_prefix}-submit"):
            _save_content(
                session_factory=session_factory,
                security_id=security_id,
                thesis_key=selected_thesis.thesis_key,
                title=None,
                created_by=None,
                summary=summary,
                driver_rows=drivers,
                risk_rows=risks,
                invalidation_rows=invalidations,
                valid_from_text=valid_from,
                authored_by=authored_by,
                approved_by=approved_by,
                approval_confirmed=approval_confirmed,
                expected_version=selected_version.version,
            )

    if selected_thesis is not None and selected_thesis.thesis_id in active_ids:
        st.subheader("Archive thesis")
        archive_confirmation = st.checkbox(
            f"Confirm archive of {selected_thesis.thesis_key}",
            key=f"archive-confirm-{selected_thesis.thesis_id}",
        )
        archived_by = st.text_input("Archived by", key=f"archive-by-{selected_thesis.thesis_id}")
        if st.button("Archive thesis", key=f"archive-{selected_thesis.thesis_id}"):
            if not archive_confirmation:
                st.error("Confirm the archive before continuing.")
            elif not archived_by.strip():
                st.error("Archived by is required.")
            else:
                try:
                    with session_factory.begin() as session:
                        repositories = repositories_for(session)
                        ThesisService(repositories.securities, repositories.theses).archive(
                            selected_thesis.thesis_key,
                            archived_by=archived_by,
                        )
                except ThesisConflictError as error:
                    st.error(str(error))
                else:
                    st.rerun()
