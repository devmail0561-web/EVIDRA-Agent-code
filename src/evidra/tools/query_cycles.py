# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Outil `query_cycles` (T5.5) : boucles de rétroaction (Tarjan, Rust), lecture seule.

Sans `concepts` : graphe entier du domaine (correctness first — borner
cacherait des cycles) ; avec : découpe bornée (`tronque` explicite). Vide =
aucun cycle (bonne nouvelle, pas un échec). Sans binaire : DEGRADE explicite.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from evidra.engine_bridge.binaire import trouver_binaire
from evidra.engine_bridge.rust import RustIndisponible
from evidra.engine_bridge.rust import interroger as interroger_rust
from evidra.kernel.contracts import Context, CostHint, Status, ToolResult, Verb
from evidra.kernel.manifest import Permission
from evidra.memory.envelope import normaliser_label
from evidra.memory.memoire import Memoire, id_triplet
from evidra.memory.sous_graphe import MAX_ARETES, MAX_NOEUDS, PROFONDEUR_DEFAUT, decouper
from evidra.tools._requetes_rust import iri_pour
from evidra.util import garde

Interroger = Callable[..., dict[str, Any]]

_LOG = logging.getLogger(__name__)


class OutilCycles:
    """Outil intégré `query_cycles` : 1 fichier = 1 outil + manifeste."""

    name = "query_cycles"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"concepts": {"type": "array"}},
    }
    output_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"cycles": {"type": "array"}},
    }
    cost_hint = CostHint(ms=50.0, calls=1)
    side_effects = frozenset({Verb.READ})
    permissions = frozenset({Permission(Verb.READ, "*")})
    channels: tuple[str, ...] = ("*",)
    requires_network = False

    def __init__(
        self,
        memoires: dict[str, Memoire],
        *,
        interroger: Interroger | None = None,
        timeout_s: float | None = None,
    ) -> None:
        from evidra.directive.schema import timeout_travailleur_defaut

        self._memoires = memoires
        self._interroger = interroger if interroger is not None else interroger_rust
        self._binaire_requis = interroger is None
        self._timeout_s = timeout_travailleur_defaut() if timeout_s is None else timeout_s

    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        """Cycles sourcés ; entrée invalide ⇒ `failed`, jamais levée."""
        return garde(self.name, lambda: self._run(ctx, args), journal=_LOG)

    def _run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        memo = self._memoires.get(ctx.domain)
        if memo is None:
            return ToolResult(
                status=Status.FAILED, payload={"motif": f"domaine inconnu : {ctx.domain!r}"}
            )
        concepts = args.get("concepts") if isinstance(args, Mapping) else None
        if concepts is not None and (
            not isinstance(concepts, list)
            or not all(isinstance(c, str) and c.strip() for c in concepts)
        ):
            return ToolResult(
                status=Status.FAILED, payload={"motif": "args.concepts : liste de chaînes exigée"}
            )
        if concepts:
            decoupe = decouper(
                memo.index,
                concepts,
                profondeur=PROFONDEUR_DEFAUT,
                max_noeuds=MAX_NOEUDS,
                max_aretes=MAX_ARETES,
            )
            ids, tronque = decoupe.ids, decoupe.tronque
        else:
            ids, tronque = tuple(sorted(memo.par_id)), 0
        if not ids:
            return ToolResult(
                status=Status.OK,
                payload={"cycles": [], "note": "aucune arête à portée", "tronque": tronque},
            )
        binaire = trouver_binaire() if self._binaire_requis else ""
        if binaire is None and self._binaire_requis:
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "cycles": [],
                    "motif": "cycles indisponibles (binaire gcn absent)",
                    "tronque": tronque,
                },
            )
        try:
            reponse = self._interroger(
                binaire, iri_pour(memo, ids), "CYCLES?", timeout_s=self._timeout_s
            )
        except (RustIndisponible, ValueError) as exc:
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "cycles": [],
                    "motif": f"cycles indisponibles : {exc}",
                    "tronque": tronque,
                },
            )
        cycles = []
        for cycle in reponse.get("cycles", []):
            if not isinstance(cycle, dict) or not isinstance(cycle.get("nodes"), list):
                continue
            noeuds = [str(n) for n in cycle["nodes"]]
            paires = (
                [(noeuds[i], noeuds[(i + 1) % len(noeuds)]) for i in range(len(noeuds))]
                if noeuds
                else []
            )
            ids = []
            for a, b in paires:
                for src, dst in ((a, b), (b, a)):
                    trouves = memo.paires.get(
                        (memo.domaine, normaliser_label(src), normaliser_label(dst)), []
                    )
                    if trouves:
                        ident = id_triplet(sorted(trouves)[0])
                        if ident in memo.par_id:
                            ids.append(ident)
                            break
            preuves = memo.preuves(ids)
            cycles.append(
                {
                    "noeuds": noeuds,
                    "espece": cycle.get("kind"),
                    "effet": cycle.get("effect"),
                    "preuves": preuves,
                    "preuves_manquantes": len(paires) - len(preuves),
                }
            )
        payload: dict[str, Any] = {"cycles": cycles, "tronque": tronque}
        if not cycles:
            if reponse.get("_status", "ok") != "ok":
                return ToolResult(
                    status=Status.DEGRADE,
                    payload={
                        "cycles": [],
                        "motif": f"moteur {reponse.get('_status')}",
                        "tronque": tronque,
                    },
                )
            payload["note"] = "aucun cycle"
        return ToolResult(status=Status.OK, payload=payload)
