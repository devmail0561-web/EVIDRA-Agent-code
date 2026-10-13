# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Outil `ingest` (T3.6) : pipeline F1 — seuils, alias, WAL, reçu.

Seul chemin d'écriture vers le graphe avec la maintenance tracée (I3) :
*nouvelle arête* (NOUVELLE), *confirmation* (même triplet, autre observation),
*idempotente* (observation revue ⇒ aucun effet, pas même WAL). Rejets comptés
par motif (`dropped`), permission `ingest` via `can()` (refus ⇒ reçu
`refused` traçable, sans effet), `trace_ref` = seq WAL max (ou `None`).

Seuils : `min_confiance` + `methodes` admises (la directive mappe
`min_extraction_method` vers cet ensemble en T4.1). Alias : table
passe-plat (identité) jusqu'en T6.5 — la normalisation casse/accents/espaces
s'applique déjà (ex. `AUTH` confirme `auth`, sans dupliquer).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from dataclasses import replace as dataclasses_replace
from typing import Any

from evidra.kernel.contracts import Context, CostHint, Record, Status, ToolResult, Verb
from evidra.kernel.gate import Policy, can, refuse
from evidra.kernel.manifest import Permission
from evidra.memory.envelope import CirCore, resume
from evidra.memory.memoire import Memoire
from evidra.memory.registres import FLUX_SOURCES
from evidra.memory.sources import Compteurs
from evidra.util import garde

FLUX_DOMAINE = "domains/{}"

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Seuils:
    """Seuils d'admission (directive, lus ici — jamais hardcodés)."""

    min_confiance: float
    methodes: frozenset[str]
    plafonds: Mapping[str, float] | None = None  # canal → confiance max (T9.1)


class OutilIngest:
    """Outil intégré `ingest` : 1 fichier = 1 outil + manifeste (§5 du plan)."""

    name = "ingest"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"noyaux": {"type": "array"}, "channel": {"type": "string"}},
        "required": ["noyaux"],
    }
    output_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "ajoutees": {"type": "integer"},
            "confirmees": {"type": "integer"},
            "idempotentes": {"type": "integer"},
            "plafonnees": {"type": "integer"},
            "dropped": {"type": "object"},
            "trace_ref": {"type": ["integer", "null"]},
        },
    }
    cost_hint = CostHint(ms=5.0, calls=1)
    side_effects = frozenset({Verb.READ, Verb.INGEST})
    permissions = frozenset({Permission(Verb.INGEST, "*")})
    channels: tuple[str, ...] = ("*",)  # canal-agnostique : le canal voyage par appel
    requires_network = False

    def __init__(
        self,
        memoires: dict[str, Memoire],
        politique: Policy,
        seuils: Seuils,
        horloge: Callable[[], str],
        fiabilite_source: Callable[[str], float] | None = None,
        alias: Mapping[tuple[str, str], str] | None = None,
    ) -> None:
        self._memoires = memoires
        self._politique = politique
        self._seuils = seuils
        self._horloge = horloge
        self._fiabilite = fiabilite_source
        self._alias = alias if alias is not None else {}

    def run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        """Pipeline F1 : porte → seuils → mémoire → WAL → reçu (jamais levée)."""
        return garde(self.name, lambda: self._run(ctx, args), journal=_LOG)

    def _run(self, ctx: Context, args: Mapping[str, Any]) -> ToolResult:
        decision = can(self._politique, self.name, Verb.INGEST, ctx.domain)
        if not decision:
            return refuse(self.name, Verb.INGEST, ctx.domain, decision.motif)
        noyaux = args.get("noyaux") if isinstance(args, Mapping) else None
        if not isinstance(noyaux, list):
            return ToolResult(status=Status.FAILED, payload={"motif": "args.noyaux : liste exigée"})
        memo = self._memoires.get(ctx.domain)
        if memo is None:
            return ToolResult(
                status=Status.FAILED, payload={"motif": f"domaine inconnu : {ctx.domain!r}"}
            )
        channel = args.get("channel", "")
        channel = channel if isinstance(channel, str) else ""
        quarantaine = args.get("quarantaine")
        quarantaine = quarantaine if isinstance(quarantaine, str) and quarantaine.strip() else None
        horodatage = self._horloge()
        flux = FLUX_DOMAINE.format(ctx.domain)
        ajoutees = confirmees = idempotentes = plafonnees = 0
        dropped: dict[str, int] = {}
        trace: int | None = None
        contributions: dict[str, dict[str, int]] = {}
        plafond = (self._seuils.plafonds or {}).get(channel, 1.0)
        for noyau in noyaux:
            if not isinstance(noyau, CirCore):
                dropped["forme-invalide"] = dropped.get("forme-invalide", 0) + 1
                continue
            if noyau.confidence > plafond:
                noyau = dataclasses_replace(noyau, confidence=plafond)
                plafonnees += 1
            if noyau.confidence < self._seuils.min_confiance:
                dropped["sous-seuil-confiance"] = dropped.get("sous-seuil-confiance", 0) + 1
                continue
            if noyau.provenance.extraction_method not in self._seuils.methodes:
                dropped["methode-refusee"] = dropped.get("methode-refusee", 0) + 1
                continue
            fiabilite = (
                self._fiabilite(noyau.provenance.ref) if self._fiabilite is not None else 0.5
            )
            issue = memo.observer(
                noyau,
                channel=channel,
                fiabilite=fiabilite,
                horodatage=horodatage,
                alias=self._alias,
                quarantaine=quarantaine,
            )
            if issue.sorte == "idempotente":
                idempotentes += 1
                continue
            seq = ctx.store.append(
                flux,
                Record(
                    stream=flux,
                    op="add_edge" if issue.sorte == "nouvelle" else "confirm",
                    key=issue.observation,
                    data={
                        "domaine": ctx.domain,
                        "triplet": list(issue.triplet),
                        "observation": issue.observation,
                        "enveloppe": dict(resume(issue.enveloppe)),
                    },
                ),
            )
            trace = seq if trace is None else max(trace, seq)
            if issue.sorte == "nouvelle":
                ajoutees += 1
            else:
                confirmees += 1
            compteur = contributions.setdefault(noyau.provenance.ref, {"c": 0, "k": 0})
            compteur["c"] += 1
            if issue.sorte == "confirmation":
                compteur["k"] += 1
        self._reporter_contributions(ctx, contributions)
        payload: dict[str, Any] = {
            "ajoutees": ajoutees,
            "confirmees": confirmees,
            "idempotentes": idempotentes,
            "plafonnees": plafonnees,
            "dropped": dropped,
            "trace_ref": trace,
        }
        if dropped:
            motifs = ", ".join(f"{k}×{v}" for k, v in sorted(dropped.items()))
            return ToolResult(
                status=Status.DEGRADE,
                payload=payload,
                warnings=(f"rejets : {motifs}",),
                trace_ref=trace,
            )
        return ToolResult(status=Status.OK, payload=payload, trace_ref=trace)

    @staticmethod
    def _reporter_contributions(ctx: Context, contributions: dict[str, dict[str, int]]) -> None:
        """Alimente `registry/sources` (T6.3) : lecture-modification-écriture.

        Une observation distincte ≈ évidence indépendante (clé §6.3 inclut
        `ref`) : `confirmation` ⇒ `confirmees_indep + 1`. Échec silencieux
        compté en `warnings` par l'appelant ? Non : best-effort tracé au log.
        """
        for ref, delta in contributions.items():
            try:
                trouve = ctx.store.lookup(FLUX_SOURCES, ref)
                brut = trouve.data.get("compteurs") if trouve is not None else None
                compteurs = Compteurs.depuis_dict(brut)
                fusionnes = Compteurs(
                    contribuees=compteurs.contribuees + delta["c"],
                    confirmees_indep=compteurs.confirmees_indep + delta["k"],
                    contredites_sup=compteurs.contredites_sup,
                )
                ctx.store.append(
                    FLUX_SOURCES,
                    Record(
                        stream=FLUX_SOURCES,
                        op="contrib",
                        key=ref,
                        data={"compteurs": fusionnes.en_dict()},
                    ),
                )
            except Exception:  # noqa: BLE001 — best-effort, l'ingestion a réussi
                _LOG.exception("compteurs source non reportés : %s", ref)
