"""Application service for immutable thesis authoring and lifecycle operations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from quant_raas.common.clock import ensure_utc, utc_now
from quant_raas.common.errors import (
    RepositoryConflictError,
    ThesisConflictError,
    ThesisNotFoundError,
    ThesisReferenceError,
)
from quant_raas.domain.enums import ThesisStatus
from quant_raas.domain.protocols import SecurityRepository, ThesisRepository
from quant_raas.domain.research import (
    Thesis,
    ThesisContent,
    ThesisVersion,
    ThesisVersionSelection,
)


@dataclass(frozen=True, slots=True)
class ThesisDetail:
    thesis: Thesis
    selection: ThesisVersionSelection


@dataclass(frozen=True, slots=True)
class CreatedThesis:
    thesis: Thesis
    version: ThesisVersion


class ThesisService:
    """Own thesis application semantics while leaving transactions to callers."""

    def __init__(
        self,
        securities: SecurityRepository,
        theses: ThesisRepository,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.securities = securities
        self.theses = theses
        self.clock = clock

    def create(
        self,
        *,
        thesis_key: str,
        security_id: UUID,
        title: str,
        content: ThesisContent,
        created_by: str,
        authored_by: str,
        approved_by: str,
        valid_from: datetime | None = None,
    ) -> CreatedThesis:
        now = ensure_utc(self.clock())
        if self.securities.get_security(security_id) is None:
            raise ThesisReferenceError(f"security {security_id} does not exist")
        activation = ensure_utc(valid_from) if valid_from is not None else now
        thesis = Thesis(
            thesis_key=thesis_key,
            security_id=security_id,
            title=title,
            created_by=created_by,
            created_at=now,
        )
        version = ThesisVersion(
            thesis_id=thesis.thesis_id,
            version=1,
            valid_from=activation,
            content=content,
            authored_by=authored_by,
            approved_by=approved_by,
            approved_at=now,
            created_at=now,
        )
        try:
            persisted_thesis = self.theses.add_thesis(thesis)
            persisted_version = self.theses.add_version(version, expected_version=0)
        except RepositoryConflictError as error:
            raise ThesisConflictError(str(error)) from error
        return CreatedThesis(thesis=persisted_thesis, version=persisted_version)

    def append_version(
        self,
        thesis_key: str,
        *,
        content: ThesisContent,
        authored_by: str,
        approved_by: str,
        expected_version: int,
        valid_from: datetime | None = None,
    ) -> ThesisVersion:
        now = ensure_utc(self.clock())
        thesis = self._get(thesis_key)
        history = tuple(self.theses.list_versions(thesis.thesis_id))
        if not history:
            raise ThesisConflictError(f"thesis {thesis_key!r} has no version history")
        latest = history[-1]
        activation = ensure_utc(valid_from) if valid_from is not None else now
        if activation < latest.valid_from:
            raise ThesisConflictError(
                "new thesis version valid_from cannot precede the latest activation"
            )
        version = ThesisVersion(
            thesis_id=thesis.thesis_id,
            version=latest.version + 1,
            valid_from=activation,
            content=content,
            authored_by=authored_by,
            approved_by=approved_by,
            approved_at=now,
            created_at=now,
        )
        try:
            return self.theses.add_version(version, expected_version=expected_version)
        except RepositoryConflictError as error:
            raise ThesisConflictError(str(error)) from error

    def detail(
        self,
        thesis_key: str,
        *,
        effective_at: datetime,
        knowledge_time: datetime,
    ) -> ThesisDetail:
        thesis = self._get(thesis_key)
        selection = self.theses.version_as_of(
            thesis,
            effective_at=effective_at,
            knowledge_time=knowledge_time,
        )
        return ThesisDetail(thesis=thesis, selection=selection)

    def list_for_security(
        self,
        security_id: UUID,
        *,
        include_archived: bool = False,
    ) -> tuple[Thesis, ...]:
        return tuple(
            self.theses.list_for_security(
                security_id,
                include_archived=include_archived,
            )
        )

    def history(self, thesis_key: str) -> tuple[ThesisVersion, ...]:
        thesis = self._get(thesis_key)
        return tuple(self.theses.list_versions(thesis.thesis_id))

    def require_reference(self, thesis_key: str, security_id: UUID) -> Thesis:
        thesis = self.theses.get_by_key(thesis_key)
        if thesis is None:
            raise ThesisReferenceError(f"thesis reference {thesis_key!r} does not exist")
        if thesis.security_id != security_id:
            raise ThesisReferenceError(
                f"thesis {thesis_key!r} does not belong to security {security_id}"
            )
        if thesis.status is ThesisStatus.ARCHIVED:
            raise ThesisReferenceError(f"thesis {thesis_key!r} is archived")
        return thesis

    def archive(self, thesis_key: str, *, archived_by: str) -> Thesis:
        now = ensure_utc(self.clock())
        thesis = self._get(thesis_key)
        try:
            return self.theses.archive(
                thesis.thesis_id,
                archived_at=now,
                archived_by=archived_by,
            )
        except RepositoryConflictError as error:
            raise ThesisConflictError(str(error)) from error

    def _get(self, thesis_key: str) -> Thesis:
        thesis = self.theses.get_by_key(thesis_key)
        if thesis is None:
            raise ThesisNotFoundError(f"thesis {thesis_key!r} does not exist")
        return thesis
