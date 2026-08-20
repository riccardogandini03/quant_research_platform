"""Point-in-time thesis selection keeps effective and knowledge time separate."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from quant_raas.domain.enums import ThesisSelectionStatus, ThesisStatus
from quant_raas.domain.research import Thesis, ThesisVersion
from quant_raas.research.thesis import active_thesis_version, select_thesis_version

pytestmark = pytest.mark.point_in_time


def test_selects_only_versions_known_at_the_cutoff(
    thesis: Thesis,
    thesis_version: ThesisVersion,
) -> None:
    version_2 = thesis_version.model_copy(
        update={
            "version": 2,
            "valid_from": datetime(2024, 1, 8, tzinfo=UTC),
            "approved_at": datetime(2024, 1, 10, tzinfo=UTC),
        }
    )

    selection = select_thesis_version(
        thesis,
        (thesis_version, version_2),
        effective_at=datetime(2024, 1, 9, tzinfo=UTC),
        knowledge_time=datetime(2024, 1, 9, tzinfo=UTC),
    )
    assert selection.status == ThesisSelectionStatus.SELECTED
    assert selection.version == thesis_version

    future_known = select_thesis_version(
        thesis,
        (thesis_version, version_2),
        effective_at=datetime(2024, 1, 9, tzinfo=UTC),
        knowledge_time=datetime(2024, 1, 10, tzinfo=UTC),
    )
    assert future_known.version == version_2


def test_reports_each_unavailable_thesis_lifecycle_state(
    thesis: Thesis,
    thesis_version: ThesisVersion,
) -> None:
    cutoff = datetime(2024, 1, 9, tzinfo=UTC)
    not_known = thesis.model_copy(update={"created_at": datetime(2024, 1, 10, tzinfo=UTC)})
    assert (
        select_thesis_version(
            not_known,
            (thesis_version,),
            effective_at=cutoff,
            knowledge_time=cutoff,
        ).status
        == ThesisSelectionStatus.NOT_KNOWN_AT_CUTOFF
    )

    not_approved = thesis_version.model_copy(
        update={"approved_at": datetime(2024, 1, 10, tzinfo=UTC)}
    )
    assert (
        select_thesis_version(
            thesis,
            (not_approved,),
            effective_at=cutoff,
            knowledge_time=cutoff,
        ).status
        == ThesisSelectionStatus.NOT_YET_APPROVED
    )

    not_effective = thesis_version.model_copy(
        update={"valid_from": datetime(2024, 1, 10, tzinfo=UTC)}
    )
    assert (
        select_thesis_version(
            thesis,
            (not_effective,),
            effective_at=cutoff,
            knowledge_time=cutoff,
        ).status
        == ThesisSelectionStatus.NOT_YET_EFFECTIVE
    )

    archived = thesis.model_copy(
        update={
            "status": ThesisStatus.ARCHIVED,
            "archived_at": datetime(2024, 1, 9, tzinfo=UTC),
            "archived_by": "pm@example.com",
        }
    )
    assert (
        select_thesis_version(
            archived,
            (thesis_version,),
            effective_at=cutoff,
            knowledge_time=cutoff,
        ).status
        == ThesisSelectionStatus.ARCHIVED_AT_CUTOFF
    )


def test_expired_newest_version_does_not_resurrect_an_older_version(
    thesis: Thesis,
    thesis_version: ThesisVersion,
) -> None:
    expired_newest = thesis_version.model_copy(
        update={
            "version": 2,
            "valid_from": datetime(2024, 1, 8, tzinfo=UTC),
            "valid_to": datetime(2024, 1, 9, tzinfo=UTC),
            "approved_at": datetime(2024, 1, 8, tzinfo=UTC),
        }
    )
    selection = select_thesis_version(
        thesis,
        (thesis_version, expired_newest),
        effective_at=datetime(2024, 1, 9, tzinfo=UTC),
        knowledge_time=datetime(2024, 1, 9, tzinfo=UTC),
    )
    assert selection.status == ThesisSelectionStatus.EXPIRED_AT_CUTOFF
    assert selection.version is None


def test_active_thesis_version_is_the_two_time_selector_wrapper(
    thesis: Thesis,
    thesis_version: ThesisVersion,
) -> None:
    assert (
        active_thesis_version(
            thesis,
            (thesis_version,),
            effective_at=datetime(2024, 1, 9, tzinfo=UTC),
            knowledge_time=datetime(2024, 1, 9, tzinfo=UTC),
        )
        == thesis_version
    )


def test_rejects_foreign_thesis_versions_before_lifecycle_selection(
    thesis: Thesis,
    thesis_version: ThesisVersion,
) -> None:
    foreign = thesis_version.model_copy(
        update={
            "thesis_id": UUID("81818181-8181-4818-8818-818181818181"),
            "version": 2,
            "valid_from": datetime(2024, 1, 8, tzinfo=UTC),
        }
    )
    with pytest.raises(ValueError, match="versions must belong to supplied thesis"):
        select_thesis_version(
            thesis,
            (thesis_version, foreign),
            effective_at=datetime(2024, 1, 9, tzinfo=UTC),
            knowledge_time=datetime(2024, 1, 9, tzinfo=UTC),
        )
