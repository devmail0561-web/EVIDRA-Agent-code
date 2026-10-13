# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Pont API↔scheduler (T8.1) : la boucle reste single-writer, jamais d'accès direct.

Le fil HTTP ne touche jamais la mémoire : il dépose un événement
(`Scheduler.deposer`, file thread-safe + `Future`) et attend avec timeout.
L'effet s'exécute dans le fil du scheduler (tick suivant au plus tard).
Correspondance : `ok`→200, `degrade`→200+warnings, `refused`→403,
`failed`→500, timeout→504, moteur absent→503.
"""

from __future__ import annotations

import concurrent.futures
import logging
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidra.kernel.contracts import Context, Status, Tool, ToolResult
from evidra.kernel.scheduler import Priorite

_LOG = logging.getLogger(__name__)

Effet = Callable[[], ToolResult]


def _defaut_travailleur() -> float:
    """Défaut canonique directive (I9), sans cycle d'import au chargement."""
    from evidra.directive.schema import timeout_travailleur_defaut

    return timeout_travailleur_defaut()


@dataclass(frozen=True, slots=True)
class ContexteAPI:
    """Ce que le fil HTTP peut utiliser : dépôt + fabriques (fil scheduler)."""

    deposer: Callable[[Priorite, Effet], Future[ToolResult]]
    domaine: str
    timeout_s: float
    construire: Callable[[str], Tool | None]
    extraire: Callable[[list[str]], ToolResult] | None
    lire_etat: Callable[[], dict[str, Any]]
    lire_alertes: Callable[[], list[dict[str, Any]]]
    ctx_memoire: Context
    timeout_travailleur_s: float = field(default_factory=_defaut_travailleur)


def deposer_attendre(ctx: ContexteAPI, niveau: Priorite, effet: Effet) -> ToolResult:
    """Dépose un effet brut et attend (timeout) ; jamais levée."""
    try:
        return ctx.deposer(niveau, effet).result(timeout=ctx.timeout_s)
    except concurrent.futures.TimeoutError:
        _LOG.warning("api timeout (%ss)", ctx.timeout_s)
        return ToolResult(
            status=Status.FAILED, payload={"motif": f"timeout ({ctx.timeout_s}s)", "timeout": True}
        )
    except Exception as exc:  # noqa: BLE001 — ne traverse jamais la frontière HTTP
        _LOG.exception("api effet")
        return ToolResult(status=Status.FAILED, payload={"motif": f"panne : {exc}"})


def executer(
    ctx: ContexteAPI,
    niveau: Priorite,
    nom_outil: str,
    args: Mapping[str, Any],
    *,
    domaine: str | None = None,
) -> ToolResult:
    """Dépose l'effet outil et attend (timeout) ; jamais levée (failed en dernier ressort)."""
    outil = ctx.construire(nom_outil)
    if outil is None:
        return ToolResult(status=Status.FAILED, payload={"motif": f"outils inconnu : {nom_outil}"})
    contexte = (
        ctx.ctx_memoire if domaine is None else Context(store=ctx.ctx_memoire.store, domain=domaine)
    )
    return deposer_attendre(ctx, niveau, lambda: outil.run(contexte, args))


def reponse(recu: ToolResult) -> tuple[int, dict[str, Any]]:
    """`ToolResult` → (HTTP, corps)."""
    corps: dict[str, Any] = {
        "status": recu.status.value,
        "payload": dict(recu.payload),
        "warnings": list(recu.warnings),
    }
    if recu.trace_ref is not None:
        corps["trace_ref"] = recu.trace_ref
    if recu.status is Status.OK:
        return 200, corps
    if recu.status is Status.DEGRADE:
        return 200, corps
    if recu.status is Status.REFUSED:
        return 403, corps
    if recu.payload.get("timeout") is True:
        return 504, corps
    return 500, corps


def contexte_depuis_rapport(
    rapport: Any, data_dir: Path, *, moteur: Any = None, timeout_s: float | None = None
) -> ContexteAPI | None:
    """Construit le contexte API depuis un démarrage (fil HTTP : dépôt seul).

    Outils construits ici mais exécutés dans le fil scheduler (effets).
    `timeout_s` explicite sinon `directive.api.timeout_s` (I9).
    `None` si boucle/magasin/directive absents (démarrage incomplet).
    """
    from evidra.engine_bridge.extract import extraire as extraire_pont
    from evidra.memory.store import etat_racine
    from evidra.tools.query_causes import OutilCauses
    from evidra.tools.query_chain import OutilChaine
    from evidra.tools.query_effects import OutilEffets
    from evidra.tools.report import OutilRapport
    from evidra.tools.validate import OutilValider

    boucle = getattr(rapport, "boucle", None)
    magasin = getattr(rapport, "magasin", None)
    directive = getattr(rapport, "directive", None)
    memoires = getattr(rapport, "memoires", None)
    registres = getattr(rapport, "registres", None)
    if boucle is None or magasin is None or directive is None or memoires is None:
        return None

    def construire(nom: str) -> Tool | None:
        if nom == "query_causes":
            return OutilCauses(memoires)
        if nom == "query_effects":
            return OutilEffets(memoires)
        if nom == "query_chain":
            return OutilChaine(memoires, timeout_s=travailleur_s)
        if nom == "validate":
            return OutilValider(memoires)
        if nom == "report":
            return OutilRapport(memoires, limite_section=directive.output.limite_section)
        if nom == "ingest":
            return getattr(rapport, "ingest", None)
        return None

    travailleur_s = directive.budgets.timeout_travailleur_s
    extraire = None
    if moteur is not None:

        def extraire(textes: list[str]) -> ToolResult:
            return extraire_pont(textes, moteur=moteur, timeout_s=travailleur_s)

    def lire_alertes() -> list[dict[str, Any]]:
        if registres is None:
            return []
        return [{"cle": c, **f} for c, f in sorted(registres.alertes_actives().items())]

    return ContexteAPI(
        deposer=boucle.deposer,
        domaine=directive.domain,
        timeout_s=timeout_s if timeout_s is not None else directive.api.timeout_s,
        timeout_travailleur_s=travailleur_s,
        construire=construire,
        extraire=extraire,
        lire_etat=lambda: etat_racine(data_dir),
        lire_alertes=lire_alertes,
        ctx_memoire=Context(store=magasin, domain=directive.domain),
    )


def effet_ingest_textes(
    ctx: ContexteAPI, outil_nom: str, textes: list[str], canal: str
) -> ToolResult:
    """F1 via API : extract → enveloppement (`api://`, horodaté) → ingest."""
    if ctx.extraire is None:
        return ToolResult(
            status=Status.FAILED, payload={"motif": "extraction indisponible sans moteur"}
        )
    outil = ctx.construire(outil_nom)
    if outil is None:
        return ToolResult(status=Status.FAILED, payload={"motif": f"outils inconnu : {outil_nom}"})

    def travail() -> ToolResult:
        from evidra.engine_bridge.provenance import envelopper, verifier, vers_noyaux

        horodatage = datetime.now(UTC).isoformat()
        recu_ext = ctx.extraire(textes)
        cirs = recu_ext.payload.get("cirs")
        if not isinstance(cirs, list):
            return ToolResult(status=Status.FAILED, payload={"motif": "extraction illisible"})
        noyaux = []
        for i, (texte, cir) in enumerate(zip(textes, cirs, strict=False)):
            try:
                enrichi = envelopper(cir, ref=f"api://{horodatage}#{i}", texte=texte)
            except (ValueError, KeyError, TypeError):
                continue
            if not verifier(enrichi, texte):
                continue
            try:
                noyaux.extend(vers_noyaux(enrichi))
            except ValueError:
                continue
        return outil.run(ctx.ctx_memoire, {"noyaux": noyaux, "channel": canal})

    return deposer_attendre(ctx, Priorite.P4, travail)
