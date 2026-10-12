# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Outil `report` (T5.8) : rapport mémoire — nouvelles, conflits, STALE, chaînes.

Depuis la mémoire (jamais du WAL brut) : relations NOUVELLE, conflits
EN RÉVISION, STALE (+INVALIDÉE comptées), chaînes surveillées (couverture par
chaîne, passées en args — la directive les fournira en T7.3). JSON ou texte,
borné (100/section, `tronque` explicite), trié (reproductible à horloge figée :
aucun horodatage produit ici). Planifiable via `report_schedule` (tâche P5/P6).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from evidra.kernel.contracts import Context, CostHint, Status, ToolResult, Verb
from evidra.kernel.manifest import Permission
from evidra.memory.ecarts import rapport_ecarts
from evidra.memory.envelope import Statut
from evidra.memory.memoire import Memoire
from evidra.util import borner, garde

LIMITE_SECTION = 100

_LOG = logging.getLogger(__name__)


class OutilRapport:
    """Outil intégré `report` : 1 fichier = 1 outil + manifeste."""

    name = "report"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "scope": {"type": "string"},
            "format": {"type": "string"},
            "chaines": {"type": "array"},
        },
    }
    output_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"sections": {"type": "object"}},
    }
    cost_hint = CostHint(ms=5.0, calls=1)
    side_effects = frozenset({Verb.READ})
    permissions = frozenset({Permission(Verb.READ, "*")})
    channels: tuple[str, ...] = ("*",)
    requires_network = False

    def __init__(self, memoires: dict[str, Memoire]) -> None:
        self._memoires = memoires

    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        """Rapport reproductible ; entrée invalide ⇒ `failed`, jamais levée."""
        return garde(self.name, lambda: self._run(ctx, args), journal=_LOG)

    def _run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        scope = args.get("scope", ctx.domain) if isinstance(args, Mapping) else ctx.domain
        format = args.get("format", "json") if isinstance(args, Mapping) else "json"
        chaines = args.get("chaines", []) if isinstance(args, Mapping) else []
        if not isinstance(scope, str) or not scope:
            return ToolResult(
                status=Status.FAILED, payload={"motif": "args.scope : chaîne non vide exigée"}
            )
        if format not in ("json", "texte"):
            return ToolResult(
                status=Status.FAILED, payload={"motif": "args.format : json|texte exigé"}
            )
        if not isinstance(chaines, list):
            return ToolResult(
                status=Status.FAILED, payload={"motif": "args.chaines : liste exigée"}
            )
        domaines = sorted(self._memoires) if scope == "all" else [scope]
        if scope != "all" and scope not in self._memoires:
            return ToolResult(
                status=Status.FAILED, payload={"motif": f"domaine inconnu : {scope!r}"}
            )
        sections: dict[str, Any] = {
            "nouvelles": [],
            "conflits": [],
            "stales": [],
            "invalidees": 0,
            "chaines": [],
            "ecarts": {},
        }
        for domaine in domaines:
            memo = self._memoires[domaine]
            sections["ecarts"][domaine] = rapport_ecarts(
                memo.entites, n_confirmee=memo.seuil_confirmee
            )
            for triplet in sorted(memo.entites):
                env = memo.entites[triplet]
                fiche = {
                    "triplet": list(triplet),
                    "confirmations": env.confirmation_count,
                    "confiance": env.cir.confidence,
                }
                if env.status is Statut.NOUVELLE:
                    sections["nouvelles"].append(fiche)
                elif env.status is Statut.EN_REVISION:
                    sections["conflits"].append(fiche)
                elif env.status is Statut.STALE:
                    sections["stales"].append(fiche)
                elif env.status is Statut.INVALIDEE:
                    sections["invalidees"] += 1
            for chaine in chaines:
                if not isinstance(chaine, list):
                    continue
                connus = sum(
                    1
                    for label in chaine
                    if isinstance(label, str)
                    and (memo.index.sortants(label) or memo.index.entrants(label))
                )
                sections["chaines"].append(
                    {"chaine": list(chaine), "couverture": [connus, len(chaine)]}
                )
        for cle in ("nouvelles", "conflits", "stales"):
            retenues, tronque = borner(
                sections[cle], LIMITE_SECTION, score=lambda f: float(f["confirmations"])
            )
            sections[cle] = {"items": retenues, "tronque": tronque}
        payload: dict[str, Any] = {"scope": scope, "sections": sections}
        if format == "texte":
            payload["texte"] = self._texte(scope, sections)
        return ToolResult(status=Status.OK, payload=payload)

    def _texte(self, scope: str, sections: dict[str, Any]) -> str:
        lignes = [f"Rapport {scope}."]
        for titre, cle in (
            ("Nouvelles", "nouvelles"),
            ("Conflits ouverts", "conflits"),
            ("Stales", "stales"),
        ):
            bloc = sections[cle]
            lignes.append(f"{titre} ({len(bloc['items'])}, tronqué {bloc['tronque']}) :")
            for fiche in bloc["items"]:
                t = fiche["triplet"]
                lignes.append(
                    f"  - {t[1]} {t[2]} {t[3]} (x{fiche['confirmations']},{fiche['confiance']:.2f})"
                )
        lignes.append(f"Invalidées : {sections['invalidees']}.")
        for domaine in sorted(sections["ecarts"]):
            ecart = sections["ecarts"][domaine]
            lignes.append(
                f"Écarts {domaine} : {ecart['entites']} entités,"
                f" p50={ecart['confirmations_p50']},"
                f" sous-seuil={ecart['sous_seuil_confirmee']}."
            )
        for chaine in sections["chaines"]:
            cov = chaine["couverture"]
            lignes.append(f"Chaîne {chaine['chaine']} : {cov[0]}/{cov[1]} couverts.")
        return "\n".join(lignes)
