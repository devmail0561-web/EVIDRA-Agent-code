# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Contrats `harness/1.0` (T1.1, noyau stdlib — ADR-0004).

Trois Protocols : `Tool`, `Adapter`, `Store`, plus les enveloppes
(`ToolResult`, `RawDoc`, `Record`, `Context`) et `HARNESS_VERSION`.
Objets immuables (`frozen=True, slots=True`) ; `ToolResult` total : aucune
exception brute ne traverse la frontière d'un outil (échec = `FAILED`).

Le noyau ne nomme aucun outil/adaptateur concret (I2).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar, NewType, Protocol, runtime_checkable

HARNESS_VERSION = "1.0"


class Status(StrEnum):
    """Statut d'un reçu d'exécution (§26 de l'étude)."""

    OK = "ok"
    DEGRADE = "degrade"
    REFUSED = "refused"  # décision de la porte `can()`, pas une erreur
    FAILED = "failed"


class Verb(StrEnum):
    """Verbes de permission appliqués par le harness (§13.3)."""

    READ = "read"
    INGEST = "ingest"
    MODIFY = "modify"
    DELETE = "delete"
    ALERT = "alert"
    EGRESS = "egress"


@dataclass(frozen=True, slots=True)
class Cost:
    """Coût mesuré d'une exécution (§26 : `cost{ms, appels}`)."""

    ms: float = 0.0
    calls: int = 0

    def __add__(self, other: Cost) -> Cost:
        return Cost(ms=self.ms + other.ms, calls=self.calls + other.calls)


@dataclass(frozen=True, slots=True)
class CostHint:
    """Coût attendu déclaré par un plugin (budgets du scheduler)."""

    ms: float = 0.0
    calls: int = 1


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Reçu obligatoire : jamais de fire-and-forget (§26.1)."""

    status: Status
    payload: Mapping[str, Any]
    warnings: tuple[str, ...] = ()
    cost: Cost = field(default_factory=Cost)
    trace_ref: int | None = None  # seq WAL du reçu, si mutation écrite


@dataclass(frozen=True, slots=True)
class RawDoc:
    """Document brut fourni par un adaptateur (donnée citée, §28.2)."""

    uri: str  # ref résolvable au moment de l'ingestion (§28.3)
    text: str  # texte cité, jamais une instruction
    channel: str = ""  # canal d'ingestion (plafonds T9.1)
    mime: str = "text/plain"
    published_at: str | None = None  # date source, jamais date d'ingestion (§6.9)
    cites: tuple[str, ...] = ()  # refs amont citées, pour le lignage (§8.5)


Cursor = NewType("Cursor", str)
"""Curseur opaque d'adaptateur (persisté via les tâches, §13.4)."""


@dataclass(frozen=True, slots=True)
class Record:
    """Enregistrement à ajouter à un stream WAL (`seq` assigné par le Store)."""

    stream: str
    op: str
    key: str
    data: Mapping[str, Any]


@runtime_checkable
class Store(Protocol):
    """Façade de persistance (implémentée par `memory/store.py`, T2.4)."""

    def append(self, stream: str, record: Record) -> int:
        """Ajoute `record`, retourne le `seq` assigné."""
        ...

    def lookup(self, stream: str, key: str) -> Record | None:
        """Lecture par clé de dédup, `None` si absent."""
        ...

    def snapshot(self, stream: str) -> None:
        """Compaction explicite du stream."""
        ...


@dataclass(frozen=True, slots=True)
class Context:
    """Contexte d'exécution passé aux outils (accès filtré par `can()`)."""

    store: Store
    domain: str
    tick: int = 0


@runtime_checkable
class Tool(Protocol):
    """Contrat d'outil : une action, des schémas, des effets déclarés."""

    name: ClassVar[str]
    version: ClassVar[str]  # semver
    harness_required: ClassVar[str]  # ex. "1.0"
    input_schema: ClassVar[Mapping[str, Any]]
    output_schema: ClassVar[Mapping[str, Any]]
    cost_hint: ClassVar[CostHint]
    side_effects: ClassVar[frozenset[Verb]]

    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        """Exécute, ne lève jamais : tout échec devient un reçu `FAILED`."""
        ...


@runtime_checkable
class Adapter(Protocol):
    """Contrat d'adaptateur : poll/ack, jamais d'écriture directe."""

    requires_network: ClassVar[bool]

    def poll(self, since: Cursor | None) -> list[RawDoc]:
        """Retourne les documents depuis `since` (au-moins-une-fois)."""
        ...

    def ack(self, cursor: Cursor) -> None:
        """Marque `cursor` comme traité (après fsync, §14)."""
        ...
