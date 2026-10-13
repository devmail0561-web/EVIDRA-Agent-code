# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Outil `query_chain` (T5.2) : Dijkstra moteur sur sous-graphe borné, jamais réécrit.

Découpe exacte (T3.4) → IR éphémère → `CHAIN` Rust (Dijkstra + Yen, ADR-0012)
→ preuves jointes aux enveloppes (ref/span/méthode/version/date). Confiance
de chaîne = produit brut moteur ; `min(prémisses)` vaut pour les dérivés
construits côté SA (T6.6, interdit par défaut — ici : pas de synthèse, les
`derives` restent une liste vide explicite). Sans binaire : DEGRADE explicite
(jamais de repli BFS qui changerait la sémantique, ADR-10).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from evidra.engine_bridge.binaire import trouver_binaire
from evidra.engine_bridge.rust import RustIndisponible, interroger_chaine, serialiser_iri
from evidra.kernel.contracts import Context, CostHint, Status, ToolResult, Verb
from evidra.kernel.manifest import Permission
from evidra.memory.envelope import normaliser_label
from evidra.memory.memoire import Memoire, id_triplet
from evidra.memory.sous_graphe import MAX_ARETES, MAX_NOEUDS, PROFONDEUR_DEFAUT, decouper
from evidra.tools._requetes_rust import aretes_pour
from evidra.util import garde

Interroger = Callable[..., dict[str, Any]]

_LOG = logging.getLogger(__name__)


class OutilChaine:
    """Outil intégré `query_chain` : 1 fichier = 1 outil + manifeste."""

    name = "query_chain"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "de": {"type": "string"},
            "vers": {"type": "string"},
            "profondeur": {"type": "integer"},
            "budget_aretes": {"type": "integer"},
        },
        "required": ["de", "vers"],
    }
    output_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"chemin": {"type": "object"}, "tronque": {"type": "integer"}},
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
        self._interroger = interroger if interroger is not None else interroger_chaine
        self._binaire_requis = interroger is None
        self._timeout_s = timeout_travailleur_defaut() if timeout_s is None else timeout_s

    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        """Chaîne Dijkstra sourcée ; entrée invalide ⇒ `failed`, jamais levée."""
        return garde(self.name, lambda: self._run(ctx, args), journal=_LOG)

    def _run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        de = args.get("de") if isinstance(args, Mapping) else None
        vers = args.get("vers") if isinstance(args, Mapping) else None
        if (
            not isinstance(de, str)
            or not de.strip()
            or not isinstance(vers, str)
            or not vers.strip()
        ):
            return ToolResult(
                status=Status.FAILED, payload={"motif": "args.de/vers : chaînes non vides exigées"}
            )
        memo = self._memoires.get(ctx.domain)
        if memo is None:
            return ToolResult(
                status=Status.FAILED, payload={"motif": f"domaine inconnu : {ctx.domain!r}"}
            )
        profondeur = (
            args.get("profondeur", PROFONDEUR_DEFAUT)
            if isinstance(args, Mapping)
            else PROFONDEUR_DEFAUT
        )
        plafond = args.get("budget_aretes", MAX_ARETES) if isinstance(args, Mapping) else MAX_ARETES
        if not isinstance(profondeur, int) or isinstance(profondeur, bool) or profondeur < 1:
            return ToolResult(
                status=Status.FAILED, payload={"motif": "profondeur entière ≥ 1 exigée"}
            )
        if not isinstance(plafond, int) or isinstance(plafond, bool) or plafond < 1:
            return ToolResult(
                status=Status.FAILED, payload={"motif": "budget_aretes entier ≥ 1 exigé"}
            )
        plafond = min(plafond, MAX_ARETES)
        decoupe = decouper(
            memo.index, [de, vers], profondeur=profondeur, max_noeuds=MAX_NOEUDS, max_aretes=plafond
        )
        if not decoupe.ids:
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "trouve": False,
                    "motif": "aucune arête à portée",
                    "chemin": None,
                    "tronque": decoupe.tronque,
                    "derives": [],
                },
            )
        binaire = trouver_binaire() if self._binaire_requis else ""
        if binaire is None and self._binaire_requis:
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "trouve": False,
                    "motif": "chaîne Dijkstra indisponible (binaire gcn absent)",
                    "chemin": None,
                    "tronque": decoupe.tronque,
                    "derives": [],
                },
            )
        iri = serialiser_iri(aretes_pour(memo, decoupe.ids))
        try:
            reponse = self._interroger(binaire, iri, de, vers, timeout_s=self._timeout_s)
        except (RustIndisponible, ValueError) as exc:
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "trouve": False,
                    "motif": f"chaîne Dijkstra indisponible : {exc}",
                    "chemin": None,
                    "tronque": decoupe.tronque,
                    "derives": [],
                },
            )
        return self._assembler(memo, decoupe.tronque, reponse)

    def _assembler(self, memo: Memoire, tronque: int, reponse: Mapping[str, Any]) -> ToolResult:
        if not reponse.get("found"):
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "trouve": False,
                    "motif": "aucun chemin causal",
                    "chemin": None,
                    "tronque": tronque,
                    "derives": [],
                },
            )
        liens = reponse.get("links", [])
        if not isinstance(liens, list) or not liens:
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "trouve": False,
                    "motif": "chemin vide",
                    "chemin": None,
                    "tronque": tronque,
                    "derives": [],
                },
            )
        ids = []
        for lien in liens:
            if not isinstance(lien, dict):
                continue
            triplet = (
                memo.domaine,
                normaliser_label(str(lien.get("from", ""))),
                str(lien.get("relation", "")),
                normaliser_label(str(lien.get("to", ""))),
            )
            ident = id_triplet(triplet)
            if ident in memo.par_id:
                ids.append(ident)
        preuves = memo.preuves(ids)
        if len(preuves) != len([li for li in liens if isinstance(li, dict)]):
            return ToolResult(
                status=Status.DEGRADE,
                payload={
                    "trouve": False,
                    "motif": "preuves non rattachables (I4)",
                    "chemin": None,
                    "tronque": tronque,
                    "derives": [],
                },
            )
        confiance = 1.0
        for preuve in preuves:
            confiance *= float(preuve["confiance"])
        return ToolResult(
            status=Status.OK,
            payload={
                "trouve": True,
                "chemin": {
                    "noeuds": [preuves[0]["source"]] + [p["cible"] for p in preuves],
                    "confiance": confiance,
                    "preuves": preuves,
                },
                "tronque": tronque,
                "derives": [],
            },
        )
