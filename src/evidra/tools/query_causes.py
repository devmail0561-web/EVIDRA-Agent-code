# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Outil `query_causes` (T5.1) : causes sourcées d'un concept.

Résolution : exact → normalisé → tokens (index) → sous-chaîne bornée (dernier
recours). Chaque cause cite ref/span/méthode/version/date (I4, 100 % des
sorties) + confiance, statut, fiabilité. Vide = « aucune source », jamais une
affirmation négative.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from evidra.kernel.contracts import Context, CostHint, Status, ToolResult, Verb
from evidra.kernel.manifest import Permission
from evidra.memory.memoire import Memoire
from evidra.util import garde

_LOG = logging.getLogger(__name__)


class OutilCauses:
    """Outil intégré `query_causes` : 1 fichier = 1 outil + manifeste."""

    name = "query_causes"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"concept": {"type": "string"}},
        "required": ["concept"],
    }
    output_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"reponses": {"type": "array"}, "resolution": {"type": "string"}},
    }
    cost_hint = CostHint(ms=5.0, calls=1)
    side_effects = frozenset({Verb.READ})
    permissions = frozenset({Permission(Verb.READ, "*")})
    channels: tuple[str, ...] = ("*",)
    requires_network = False

    def __init__(self, memoires: dict[str, Memoire]) -> None:
        self._memoires = memoires

    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        """Causes sourcées ; entrée invalide ⇒ `failed`, jamais levée."""
        return garde(self.name, lambda: self._run(ctx, args), journal=_LOG)

    def _run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        concept = args.get("concept") if isinstance(args, Mapping) else None
        if not isinstance(concept, str) or not concept.strip():
            return ToolResult(
                status=Status.FAILED, payload={"motif": "args.concept : chaîne non vide exigée"}
            )
        memo = self._memoires.get(ctx.domain)
        if memo is None:
            return ToolResult(
                status=Status.FAILED, payload={"motif": f"domaine inconnu : {ctx.domain!r}"}
            )
        touche = False
        try:
            ids, resolution, touche = memo.rechercher("causes", concept)
        except ValueError as exc:
            return ToolResult(status=Status.FAILED, payload={"motif": str(exc)})
        reponses = memo.preuves(ids)
        payload: dict[str, Any] = {
            "concept": concept,
            "reponses": reponses,
            "resolution": resolution,
            "cache": "hit" if touche else "miss",
        }
        if not reponses:
            payload["note"] = "aucune source"
        return ToolResult(status=Status.OK, payload=payload)
