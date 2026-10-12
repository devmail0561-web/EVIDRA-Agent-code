# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Outil `validate` (T5.3) : claim → CONFIRMED / UNCONFIRMED / CONTRADICTED.

Entrée : triplet structuré ou texte (extrait en CIR candidat via l'extracteur
injecté ; sans extracteur : DEGRADE, jamais d'invention). Table fermée des
opposés (reprise §5, les deux flexions) + négation explicite du même lien ;
hors table = UNCONFIRMED. Arêtes quarantinées exclues (I11/T9.5). Granularité :
le déni explicite (`negated`) prime, puis (confirmations, confiance) décroissants,
nom de relation en bris d'égalité (déterministe ; la granularité relationnelle
fine reste à spécifier). Taux de CONFIRMED correct : mesuré en phase 10 (gold).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

from evidra.kernel.contracts import Context, CostHint, Status, ToolResult, Verb
from evidra.kernel.manifest import Permission
from evidra.memory.envelope import normaliser_label
from evidra.memory.memoire import Memoire, Triplet
from evidra.util import garde

_LOG = logging.getLogger(__name__)

# Table fermée §5 (les deux flexions, explicite — jamais étendue sans ADR).
OPPOSES: Mapping[str, frozenset[str]] = {
    "cause": frozenset({"prevent"}),
    "prevent": frozenset({"cause"}),
    "causes": frozenset({"prevents"}),
    "prevents": frozenset({"causes"}),
    "enable": frozenset({"block"}),
    "block": frozenset({"enable"}),
    "enables": frozenset({"blocks"}),
    "blocks": frozenset({"enables"}),
}

Extraire = Callable[[list[str]], ToolResult]


class OutilValider:
    """Outil intégré `validate` : 1 fichier = 1 outil + manifeste."""

    name = "validate"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"claim": {"type": ["string", "object"]}},
    }
    output_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"verdict": {"type": "string"}},
    }
    cost_hint = CostHint(ms=10.0, calls=1)
    side_effects = frozenset({Verb.READ})
    permissions = frozenset({Permission(Verb.READ, "*")})
    channels: tuple[str, ...] = ("*",)
    requires_network = False

    def __init__(self, memoires: dict[str, Memoire], *, extraire: Extraire | None = None) -> None:
        self._memoires = memoires
        self._extraire = extraire

    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        """Verdict sourcé ; entrée invalide ⇒ `failed`, jamais levée."""
        return garde(self.name, lambda: self._run(ctx, args), journal=_LOG)

    def _run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        brut = args.get("claim") if isinstance(args, Mapping) else None
        triplet = self._triplet_claim(brut)
        if triplet is None:
            if isinstance(brut, str):
                return ToolResult(
                    status=Status.DEGRADE,
                    payload={
                        "verdict": "UNCONFIRMED",
                        "motif": "claim inexploitable sans extraction",
                    },
                )
            return ToolResult(
                status=Status.FAILED, payload={"motif": "args.claim : texte ou triplet exigé"}
            )
        memo = self._memoires.get(ctx.domain)
        if memo is None:
            return ToolResult(
                status=Status.FAILED, payload={"motif": f"domaine inconnu : {ctx.domain!r}"}
            )
        return self._verdict(memo, triplet)

    def _triplet_claim(self, brut: Any) -> Triplet | None:
        if isinstance(brut, Mapping):
            src, rel, dst = (
                brut.get("source"),
                brut.get("relation"),
                brut.get("cible", brut.get("target")),
            )
            if (
                isinstance(src, str)
                and src.strip()
                and isinstance(rel, str)
                and rel.strip()
                and isinstance(dst, str)
                and dst.strip()
            ):
                return ("", normaliser_label(src), rel.strip(), normaliser_label(dst))
            return None
        if isinstance(brut, str) and brut.strip() and self._extraire is not None:
            recu = self._extraire([brut])
            if recu.status is Status.FAILED:
                return None
            for cir in recu.payload.get("cirs", []):
                triplet = _triplet_cir(cir)
                if triplet is not None:
                    return triplet
        return None

    def _verdict(self, memo: Memoire, triplet: Triplet) -> ToolResult:
        _, src, rel, dst = triplet
        env = memo.entites.get((memo.domaine, src, rel, dst))
        if env is not None and env.quarantine is None and not env.cir.negated:
            return ToolResult(
                status=Status.OK,
                payload={
                    "verdict": "CONFIRMED",
                    "source": env.cir.provenance.ref,
                    "confiance": env.cir.confidence,
                    "confirmations": env.confirmation_count,
                },
            )
        contradicteurs = []
        for t in memo.paires.get((memo.domaine, src, dst), []):
            cand = memo.entites.get(t)
            if cand is None or cand.quarantine is not None:
                continue
            if t[2] == rel and cand.cir.negated:
                contradicteurs.append((0, cand))
            elif t[2] in OPPOSES.get(rel, frozenset()):
                contradicteurs.append((1, cand))
        if contradicteurs:
            _, env = min(
                contradicteurs,
                key=lambda re: (
                    re[0],
                    -re[1].confirmation_count,
                    -re[1].cir.confidence,
                    re[1].cir.relation,
                ),
            )
            return ToolResult(
                status=Status.OK,
                payload={
                    "verdict": "CONTRADICTED",
                    "source": env.cir.provenance.ref,
                    "confiance": env.cir.confidence,
                },
            )
        return ToolResult(
            status=Status.OK,
            payload={
                "verdict": "UNCONFIRMED",
                "motif": "ni preuve ni réfutation (jamais « faux »)",
            },
        )


def _triplet_cir(cir: Any) -> Triplet | None:
    """Premier bord d'un CIR candidat (labels résolus, sans enveloppement)."""
    if not isinstance(cir, dict):
        return None
    noeuds = cir.get("nodes", [])
    labels = {n["id"]: str(n.get("label", "")) for n in noeuds if isinstance(n, dict) and "id" in n}
    for e in cir.get("edges", []):
        if isinstance(e, (list, tuple)) and len(e) == 3 and isinstance(e[2], dict):
            rel = e[2].get("relation")
            if isinstance(rel, str) and rel.strip() and e[0] in labels and e[1] in labels:
                return (
                    "",
                    normaliser_label(labels[e[0]]),
                    rel.strip(),
                    normaliser_label(labels[e[1]]),
                )
    return None
