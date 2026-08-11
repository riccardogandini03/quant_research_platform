"""Deterministic filing-section comparison used before any AI synthesis."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SectionChange:
    section: str
    change_ratio: float
    added_lines: tuple[str, ...]
    removed_lines: tuple[str, ...]


_HEADING = re.compile(r"^(?:item\s+\d+[a-z]?\.?\s*)?([A-Z][A-Z\s&/-]{3,})$", re.MULTILINE)


def segment_sections(text: str) -> dict[str, str]:
    """Split common all-caps filing headings without inventing a taxonomy."""

    matches = list(_HEADING.finditer(text))
    if not matches:
        return {"DOCUMENT": text.strip()} if text.strip() else {}
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        name = " ".join(match.group(1).split()).title()
        body = text[start:end].strip()
        if body:
            sections[name] = body
    return sections


def compare_filings(previous: str, current: str) -> tuple[SectionChange, ...]:
    """Return auditable line changes by section, ordered by material change."""

    old_sections = segment_sections(previous)
    new_sections = segment_sections(current)
    changes: list[SectionChange] = []
    for section in sorted(set(old_sections) | set(new_sections)):
        old_lines = old_sections.get(section, "").splitlines()
        new_lines = new_sections.get(section, "").splitlines()
        matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
        added: list[str] = []
        removed: list[str] = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in {"replace", "delete"}:
                removed.extend(line.strip() for line in old_lines[i1:i2] if line.strip())
            if tag in {"replace", "insert"}:
                added.extend(line.strip() for line in new_lines[j1:j2] if line.strip())
        if added or removed:
            changes.append(
                SectionChange(
                    section=section,
                    change_ratio=1.0 - matcher.ratio(),
                    added_lines=tuple(added),
                    removed_lines=tuple(removed),
                )
            )
    return tuple(sorted(changes, key=lambda item: (-item.change_ratio, item.section)))
