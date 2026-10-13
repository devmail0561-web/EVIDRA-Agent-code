# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Outil `query_gaps` (T5.5) : lacunes sur chaînes surveillées, lecture seule.

Ne s'applique QU'AUX chaînes surveillées par la directive : `chaine` requise
(fail-closed, pas de pêche globale). Découpe bornée autour de la chaîne,
`GAPS?` Rust, lacunes jointes (provenance) + nœuds non résolus. Vide = pas de
lacune (bonne nouvelle). Sans binaire : DEGRADE explicite.
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
from evidra.memory.memoire import Memoire
from evidra.memory.sous_graphe import MAX_ARETES, MAX_NOEUDS, decouper
from evidra.tools._requetes_rust import iri_pour, preuves_pour
from evidra.util import garde

Interroger = Callable[..., dict[str, Any]]

_LOG = logging.getLogger(__name__)


class OutilLacunes:
    """Outil intégré `query_gaps` : 1 fichier = 1 outil + manifeste."""

    name = "query_gaps"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"chaine": {"type": "array"}},
        "required": ["chaine"],
    }
    output_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"lacunes": {"type": "array"}},
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
        profondeur: int | None = None,
    ) -> None:
        from evidra.directive.schema import profondeur_gaps_defaut, timeout_travailleur_defaut

        self._memoires = memoires
        self._interroger = interroger if interroger is not None else interroger_rust
        self._timeout_s = timeout_travailleur_defaut() if timeout_s is None else timeout_s
        self._profondeur = profondeur_gaps_defaut() if profondeur is None else profondeur

    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        """Lacunes sourcées d'une chaîne surveillée ; jamais levée."""
        return garde(self.name, lambda: self._run(ctx, args), journal=_LOG)

    def _run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        chaine = args.get("chaine") if isinstance(args, Mapping) else None
        if (
            not isinstance(chaine, list)
            or not chaine
            or not all(isinstance(c, str) and c.strip() for c in chaine)
        ):
            return ToolResult(
                status=Status.FAILED,
                payload={"motif": "args.chaine : concepts surveillés exigés (liste non vide)"},
            )
        memo = self._memoires.get(ctx.domain)
        if memo is None:
            return ToolResult(
                status=Status.FAILED, payload={"motif": f"domaine inconnu : {ctx.domain!r}"}
            )
        decoupe = decouper(
            memo.index,
            chaine,
            profondeur=self._profondeur,
            max_noeuds=MAX_NOEUDS,
            max_aretes=MAX_ARETES,
        )
        if not decoupe.ids:
            return ToolResult(
                status=Status.DEGRADE,
                payload={"lacunes": [], "motif": "chaîne hors graphe", "tronque": decoupe.tronque},
            )
        binaire = trouver_binaire()
        if binaire is None:
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "lacunes": [],
                    "motif": "lacunes indisponibles (binaire gcn absent)",
                    "tronque": decoupe.tronque,
                },
            )
        try:
            reponse = self._interroger(
                binaire, iri_pour(memo, decoupe.ids), "GAPS?", timeout_s=self._timeout_s
            )
        except (RustIndisponible, ValueError) as exc:
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "lacunes": [],
                    "motif": f"lacunes indisponibles : {exc}",
                    "tronque": decoupe.tronque,
                },
            )
        lacunes = []
        for arete in reponse.get("gap_edges", []):
            if not isinstance(arete, dict):
                continue
            preuves, manquantes = preuves_pour(memo, [arete])
            lacunes.append(
                {
                    "de": arete.get("from"),
                    "vers": arete.get("to"),
                    "relation": arete.get("relation"),
                    "preuves": preuves,
                    "preuves_manquantes": manquantes,
                }
            )
        payload: dict[str, Any] = {
            "chaine": list(chaine),
            "lacunes": lacunes,
            "noeuds_non_resolus": reponse.get("unresolved_nodes", 0),
            "tronque": decoupe.tronque,
        }
        if not lacunes:
            if reponse.get("_status", "ok") != "ok":
                return ToolResult(
                    status=Status.DEGRADE,
                    payload={
                        "lacunes": [],
                        "motif": f"moteur {reponse.get('_status')}",
                        "tronque": decoupe.tronque,
                    },
                )
            payload["note"] = "aucune lacune"
        return ToolResult(status=Status.OK, payload=payload)
