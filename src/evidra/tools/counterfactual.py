# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Outil `counterfactual` (T5.5 + patch P6) : do-calculus, ÉTIQUETÉ assertion.

Pearl do-calculus du moteur sur sous-graphe borné. Calcul sur assertions
sourcées (avec preuves), SANS contrôle de confondeurs ni modèle structurel —
étiqueté comme tel dans chaque reçu, jamais présenté comme fait établi (§2).
Lecture seule, comme toutes les coquilles `reason`.
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
from evidra.memory.sous_graphe import MAX_ARETES, MAX_NOEUDS, PROFONDEUR_DEFAUT, decouper
from evidra.tools._requetes_rust import iri_pour, preuves_pour

Interroger = Callable[..., dict[str, Any]]

_LOG = logging.getLogger(__name__)

AVERTISSEMENT = (
    "calcul sur assertions sourcées (avec preuves), sans contrôle de confondeurs "
    "ni modèle structurel — étiqueté comme tel, jamais présenté comme fait établi (§2)"
)


class OutilContrefactuel:
    """Outil intégré `counterfactual` : 1 fichier = 1 outil + manifeste."""

    name = "counterfactual"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"concept": {"type": "string"}},
        "required": ["concept"],
    }
    output_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"effets": {"type": "array"}, "avertissement": {"type": "string"}},
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
        """Effets si le concept n'avait pas eu lieu (étiquetés) ; jamais levée."""
        try:
            return self._run(ctx, args)
        except Exception as exc:  # noqa: BLE001 — l'outil ne lève jamais
            _LOG.exception("panne outil counterfactual")
            return ToolResult(
                status=Status.FAILED,
                payload={"motif": f"panne counterfactual : {exc}", "avertissement": AVERTISSEMENT},
            )

    def _run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        concept = args.get("concept") if isinstance(args, Mapping) else None
        if not isinstance(concept, str) or not concept.strip():
            return ToolResult(
                status=Status.FAILED,
                payload={
                    "motif": "args.concept : chaîne non vide exigée",
                    "avertissement": AVERTISSEMENT,
                },
            )
        memo = self._memoires.get(ctx.domain)
        if memo is None:
            return ToolResult(
                status=Status.FAILED,
                payload={
                    "motif": f"domaine inconnu : {ctx.domain!r}",
                    "avertissement": AVERTISSEMENT,
                },
            )
        decoupe = decouper(
            memo.index,
            [concept],
            profondeur=PROFONDEUR_DEFAUT,
            max_noeuds=MAX_NOEUDS,
            max_aretes=MAX_ARETES,
        )
        if not decoupe.ids:
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "concept": concept,
                    "effets": [],
                    "motif": "concept hors graphe",
                    "avertissement": AVERTISSEMENT,
                    "tronque": decoupe.tronque,
                },
            )
        binaire = trouver_binaire()
        if binaire is None and self._binaire_requis:
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "concept": concept,
                    "effets": [],
                    "motif": "contrefactuel indisponible (binaire gcn absent)",
                    "avertissement": AVERTISSEMENT,
                    "tronque": decoupe.tronque,
                },
            )
        try:
            reponse = self._interroger(
                binaire,
                iri_pour(memo, decoupe.ids),
                f"COUNTERFACTUAL {concept.strip()}?",
                timeout_s=self._timeout_s,
            )
        except (RustIndisponible, ValueError) as exc:
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "concept": concept,
                    "effets": [],
                    "motif": f"contrefactuel indisponible : {exc}",
                    "avertissement": AVERTISSEMENT,
                    "tronque": decoupe.tronque,
                },
            )
        effets = []
        for effet in reponse.get("actual_effects", []):
            if not isinstance(effet, dict):
                continue
            preuves, manquantes = preuves_pour(memo, [effet])
            effets.append(
                {
                    "cible": effet.get("to"),
                    "relation": effet.get("relation"),
                    "confiance": effet.get("confidence"),
                    "preuves": preuves,
                    "preuves_manquantes": manquantes,
                }
            )
        return ToolResult(
            status=Status.OK,
            payload={
                "concept": concept,
                "cible": reponse.get("target", concept),
                "effets": effets,
                "uniques": reponse.get("unique_effects", []),
                "avertissement": AVERTISSEMENT,
                "tronque": decoupe.tronque,
            },
        )
