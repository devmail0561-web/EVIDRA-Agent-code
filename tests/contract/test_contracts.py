# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T1.1 — suite de contrat : un plugin factice conforme est accepté, tout
plugin non conforme (champ manquant, mauvais type) est rejeté.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from evidra.kernel.contracts import (
    HARNESS_VERSION,
    Adapter,
    Context,
    CostHint,
    Cursor,
    RawDoc,
    Record,
    Status,
    Store,
    Tool,
    ToolResult,
    Verb,
)


class _BonOutil:
    name = "outil-factice"
    version = "0.1.0"
    harness_required = HARNESS_VERSION
    input_schema: Mapping[str, Any] = {}
    output_schema: Mapping[str, Any] = {}
    cost_hint = CostHint(ms=1.0)
    side_effects = frozenset({Verb.READ})

    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        return ToolResult(status=Status.OK, payload={"echo": dict(args)})


class _OutilSansRun:
    name = "sans-run"
    version = "0.1.0"
    harness_required = HARNESS_VERSION
    input_schema: Mapping[str, Any] = {}
    output_schema: Mapping[str, Any] = {}
    cost_hint = CostHint()
    side_effects = frozenset()


class _MauvaisEffets:
    name = "mauvais-effets"
    version = "0.1.0"
    harness_required = HARNESS_VERSION
    input_schema: Mapping[str, Any] = {}
    output_schema: Mapping[str, Any] = {}
    cost_hint = CostHint()
    side_effects = frozenset({"read"})  # type: ignore[arg-type] # str, pas Verb

    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        return ToolResult(status=Status.OK, payload={})


class _BonAdaptateur:
    requires_network = False

    def poll(self, since: Cursor | None) -> list[RawDoc]:
        return []

    def ack(self, cursor: Cursor) -> None:
        return None


class _AdaptateurSansFlag:
    def poll(self, since: Cursor | None) -> list[RawDoc]:
        return []

    def ack(self, cursor: Cursor) -> None:
        return None


class _BonStore:
    def __init__(self) -> None:
        self._seq = 0

    def append(self, stream: str, record: Record) -> int:
        self._seq += 1
        return self._seq

    def lookup(self, stream: str, key: str) -> Record | None:
        return None

    def snapshot(self, stream: str) -> None:
        return None


def _verdicts_tool(cls: type) -> list[str]:
    verdicts: list[str] = []
    for attr in (
        "name",
        "version",
        "harness_required",
        "input_schema",
        "output_schema",
        "cost_hint",
        "side_effects",
        "run",
    ):
        if not hasattr(cls, attr):
            verdicts.append(f"champ manquant: {attr}")
    effets = getattr(cls, "side_effects", None)
    if effets is not None and (
        not isinstance(effets, frozenset) or not all(isinstance(v, Verb) for v in effets)
    ):
        verdicts.append("side_effects doit être frozenset[Verb]")
    hint = getattr(cls, "cost_hint", None)  # noqa: B009 — l'attribut peut manquer
    if hint is not None and not isinstance(hint, CostHint):
        verdicts.append("cost_hint doit être CostHint")
    return verdicts


def test_outil_conforme_accepte():
    assert isinstance(_BonOutil(), Tool)
    assert _verdicts_tool(_BonOutil) == []


def test_outil_sans_run_rejete():
    assert not isinstance(_OutilSansRun(), Tool)
    assert _verdicts_tool(_OutilSansRun) == ["champ manquant: run"]


def test_outil_mauvais_effets_rejete():
    assert _verdicts_tool(_MauvaisEffets) == ["side_effects doit être frozenset[Verb]"]


def test_adaptateur_conforme_accepte():
    assert isinstance(_BonAdaptateur(), Adapter)


def test_adaptateur_sans_flag_rejete():
    assert not isinstance(_AdaptateurSansFlag(), Adapter)


def test_store_conforme_accepte():
    store = _BonStore()
    assert isinstance(store, Store)
    assert store.append("s", Record(stream="s", op="add", key="k", data={})) == 1
    assert store.lookup("s", "k") is None
