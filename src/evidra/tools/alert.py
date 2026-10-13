# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Outil `alert` (T7.2, P1) : conditions pures → dédup → JSONL + egress.

Évalue les conditions T7.1 sur les mémoires vivantes (sans E/S lourde),
lève en `registry/alertes`, émet (JSONL local toujours ; `alert_endpoint`
en egress best-effort — hors ligne ⇒ `degrade` + conservée, jamais bloqué).
`run` ne lève jamais (garde). Dédup : `doit_emettre` + `noter_envoi`.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from evidra.kernel.contracts import Context, CostHint, Status, ToolResult, Verb
from evidra.kernel.manifest import Permission
from evidra.memory.memoire import Memoire
from evidra.memory.registres import Registres
from evidra.memory.sources import SeuilsSources, bilan
from evidra.monitor.alerts import doit_emettre
from evidra.monitor.conditions import (
    Condition,
    conflit_non_resolu,
    haute_confiance_invalidee,
    nouvelle_relation,
    source_suspecte,
)
from evidra.output.alert import formater_alerte
from evidra.util import garde

_LOG = logging.getLogger(__name__)


class OutilAlert:
    """Outil intégré `alert` : 1 fichier = 1 outil + manifeste."""

    name = "alert"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {"type": "object", "properties": {}}
    output_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "levees": {"type": "array"},
            "emises": {"type": "array"},
            "degrade": {"type": "array"},
        },
    }
    cost_hint = CostHint(ms=5.0, calls=1)
    side_effects = frozenset({Verb.READ, Verb.ALERT})
    permissions = frozenset({Permission(Verb.READ, "*"), Permission(Verb.ALERT, "*")})
    channels: tuple[str, ...] = ("*",)
    requires_network = False  # l'egress est best-effort, jamais exigé

    def __init__(
        self,
        memoires: dict[str, Memoire],
        registres: Registres,
        motifs: list[str],
        seuil_invalidation: float,
        seuils_sources: SeuilsSources,
        sortie: Path,
        horloge: Callable[[], str],
        *,
        endpoint: str | None = None,
        fenetre_s: int | None = None,
        timeout_egress_s: float | None = None,
        egress_hotes: list[str] | tuple[str, ...] | set[str] | None = None,
    ) -> None:
        from evidra.directive.schema import fenetre_alertes_defaut, timeout_egress_defaut

        self._memoires = memoires
        self._registres = registres
        self._motifs = list(motifs)
        self._seuil_invalidation = seuil_invalidation
        self._seuils_sources = seuils_sources
        self._sortie = sortie
        self._horloge = horloge
        self._endpoint = endpoint
        self._fenetre_s = fenetre_alertes_defaut() if fenetre_s is None else fenetre_s
        self._timeout_egress_s = (
            timeout_egress_defaut() if timeout_egress_s is None else timeout_egress_s
        )
        self._egress_hotes = egress_hotes

    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        """Évalue → lève → émet ; jamais levée."""
        return garde(self.name, lambda: self._run(ctx, args), journal=_LOG)

    def evaluer(self, domaine: str) -> list[Condition]:
        """Conditions pures sur un domaine (sans E/S, testable)."""
        memo = self._memoires.get(domaine)
        if memo is None:
            return []
        trouvees = []
        for triplet, env in sorted(memo.entites.items()):
            cond = nouvelle_relation(triplet, self._motifs)
            if cond is not None:
                trouvees.append(cond)
            invalidee = haute_confiance_invalidee(
                triplet, env.status.value, env.cir.confidence, seuil=self._seuil_invalidation
            )
            if invalidee is not None:
                trouvees.append(invalidee)
            conflit = conflit_non_resolu(triplet, env.status.value)
            if conflit is not None:
                trouvees.append(conflit)
        return trouvees

    def _sources_suspectes(self, domaine: str) -> list[Condition]:
        """Sources `suspect` au registre parmi les refs du domaine (E/S)."""
        memo = self._memoires.get(domaine)
        if memo is None:
            return []
        refs = {env.cir.provenance.ref for env in memo.entites.values()}
        trouvees = []
        for ref in sorted(refs):
            fiche = self._registres.source(ref)
            if fiche is None:
                continue
            statut = bilan(fiche, self._seuils_sources)["statut"]
            cond = source_suspecte(ref, statut)
            if cond is not None:
                trouvees.append(cond)
        return trouvees

    def _run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        del args
        maintenant = self._horloge()
        levees, emises, degrades = [], [], []
        for domaine in sorted(self._memoires):
            conditions = self.evaluer(domaine) + self._sources_suspectes(domaine)
            for cond in conditions:
                fiche = self._registres.alerte(cond.cle)
                if fiche is None:
                    self._registres.lever_alerte(
                        cond.cle,
                        {
                            "nom": cond.nom,
                            "severite": cond.severite,
                            "domaine": domaine,
                            "detail": dict(cond.detail),
                            "levee_a": maintenant,
                        },
                    )
                    levees.append(cond.cle)
                if doit_emettre(
                    self._registres.dernier_envoi(cond.cle),
                    maintenant_iso=maintenant,
                    fenetre_s=self._fenetre_s,
                    acquittee=(self._registres.alerte(cond.cle) or {}).get("etat") == "acquittee",
                ):
                    payload = formater_alerte(
                        ToolResult(status=Status.OK, payload={}),
                        severite=cond.severite,
                        condition=cond.nom,
                    )
                    payload["cle"] = cond.cle
                    payload["domaine"] = domaine
                    self._emettre(payload)
                    self._registres.noter_envoi(cond.cle, maintenant)
                    emises.append(cond.cle)
                    if self._endpoint is not None:
                        motif = self._egresser(payload)
                        if motif is not None:
                            degrades.append(motif)
        return ToolResult(
            status=Status.DEGRADE if degrades else Status.OK,
            payload={"levees": levees, "emises": emises, "degrade": sorted(set(degrades))},
        )

    def _emettre(self, payload: Mapping[str, Any]) -> None:
        self._sortie.parent.mkdir(parents=True, exist_ok=True)
        with open(self._sortie, "a", encoding="utf-8") as flux:
            flux.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _egresser(self, payload: Mapping[str, Any]) -> str | None:
        """POST best-effort ; `None` si envoyé, motif dégradé sinon (T9.9 whitelist)."""
        assert self._endpoint is not None
        from evidra.security.egress import verifier_egress

        ok, motif = verifier_egress(self._endpoint, self._egress_hotes)
        if not ok:
            return motif
        try:
            requete = urllib.request.Request(
                self._endpoint,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(requete, timeout=self._timeout_egress_s) as reponse:
                if 200 <= reponse.status < 300:
                    return None
                return f"egress {self._endpoint} : HTTP {reponse.status}"
        except Exception as exc:  # noqa: BLE001 — hors ligne ⇒ dégradé, jamais bloqué
            _LOG.debug("egress alerte impossible : %s", exc)
            return f"egress {self._endpoint} : {exc}"
