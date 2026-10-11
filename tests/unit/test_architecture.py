# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T1.7 — non-régression architecturale : un outil et un adaptateur factices,
installés uniquement via les contrats (sans toucher au noyau), exécutent un
tick complet. Si ce test exigeait une modification de `kernel/`, le design
du plugin serait fautif. Le jeu de modules du noyau est en outre gelé.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from evidra.kernel.contracts import (
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
from evidra.kernel.gate import Policy, Rule, can
from evidra.kernel.registry import Registry
from evidra.kernel.scheduler import Priorite, Scheduler

MODULES_NOYAU = frozenset({"contracts", "gate", "manifest", "registry", "scheduler"})


class _OutilFactice:
    name = "outil-factice"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {}
    output_schema: Mapping[str, Any] = {}
    cost_hint = CostHint()
    side_effects = frozenset({Verb.READ})
    requires_network = False
    permissions = [{"verb": "read", "scope": "*"}]
    channels = ["test"]
    cost_hint_brut = {"ms": 0.0, "calls": 1}

    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        return ToolResult(status=Status.OK, payload={"domaine": ctx.domain})


class _AdaptateurFactice:
    requires_network = False

    def poll(self, since: Cursor | None) -> list[RawDoc]:
        return [RawDoc(uri="test://doc", text="cause texte", channel="test")]

    def ack(self, cursor: Cursor) -> None:
        return None


class _StoreBac:
    def __init__(self) -> None:
        self._seq = 0

    def append(self, stream: str, record: Record) -> int:
        self._seq += 1
        return self._seq

    def lookup(self, stream: str, key: str) -> Record | None:
        return None

    def snapshot(self, stream: str) -> None:
        return None


def test_tick_complet_sans_toucher_au_noyau():
    assert isinstance(_OutilFactice(), Tool)
    assert isinstance(_StoreBac(), Store)
    registre = Registry()
    registre.discover(
        {"evidra_tools": [SimpleNamespace(name="outil-factice", load=lambda: _OutilFactice)]}
    )
    cle = "evidra_tools:outil-factice"
    assert registre.approve(cle, _OutilFactice).state.value == "validated"
    registre.enable(cle)
    registre.start(cle)
    policy = Policy(allowed=frozenset({Rule("outil-factice", Verb.READ, "*")}))
    assert can(policy, "outil-factice", Verb.READ, "test")
    ctx = Context(store=_StoreBac(), domain="test")
    ordonnanceur = Scheduler()
    ordonnanceur.enregistrer(Priorite.P3, lambda: True, lambda: _OutilFactice().run(ctx, {}))
    (recu,) = ordonnanceur.tour().recus
    assert recu.niveau is Priorite.P3
    assert recu.resultat.status is Status.OK
    assert recu.resultat.payload == {"domaine": "test"}
    docs = _AdaptateurFactice().poll(None)
    assert docs[0].uri == "test://doc"


def test_jeu_de_modules_du_noyau_gele():
    noyau = Path(__file__).resolve().parent.parent.parent / "src" / "evidra" / "kernel"
    trouves = frozenset(p.stem for p in noyau.glob("*.py") if p.stem != "__init__")
    assert trouves == MODULES_NOYAU
