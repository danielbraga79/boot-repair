from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvidenceViewModel:
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanViewModel:
    title: str
    confidence: str
    actions: tuple[str, ...]
    justifications: tuple[str, ...]
    risks: tuple[str, ...]
    preconditions: tuple[str, ...]
    rollback: tuple[str, ...]
