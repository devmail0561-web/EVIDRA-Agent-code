# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Démarrage en cinq phases (T4.5) : manifeste → WAL → registres → moteur → boucle.

Chaque phase écrit un rapport structuré. Divergence manifeste (harness ou
moteur changé sous les données) ⇒ `degraded` explicite + motif, jamais de
poursuite silencieuse. Verrou pris ⇒ refus net (`DemarrageError`, une seule
instance). Directive illisible ⇒ refus net. `pending` conversationnel : phase
10 (F7), pas ici.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidra import __version__ as VERSION_SA  # noqa: N812 — alias constant volontaire
from evidra.boucle import Boucle
from evidra.directive.loader import charger
from evidra.directive.reload import Surveillant
from evidra.directive.schema import Directive
from evidra.engine_bridge.travailleur import lancer
from evidra.kernel.scheduler import Budgets, Scheduler
from evidra.memory.memoire import Memoire, memoire_depuis_etat
from evidra.memory.registres import Registres
from evidra.memory.store import Magasin, StoreError
from evidra.tools.ingest import OutilIngest, Seuils
from evidra.util import version_moteur

NOM_MANIFASTE = "sa_manifest.json"

_LOG = logging.getLogger(__name__)


class DemarrageError(Exception):
    """Démarrage impossible (verrou pris, directive illisible)."""


@dataclass(frozen=True, slots=True)
class RapportDemarrage:
    """Bilan : gouvernance + objets vivants (boucle, magasin, registres, mémoires)."""

    degraded: bool
    motifs: tuple[str, ...]
    phases: Mapping[str, Mapping[str, Any]]
    boucle: Boucle | None
    magasin: Magasin | None
    registres: Registres | None
    memoires: Mapping[str, Memoire]
    directive: Directive | None
    ingest: OutilIngest | None  # piloté par F1 (tâches/effet P4, à brancher)


def _horloge_defaut() -> str:
    return datetime.now(UTC).isoformat()


def _seuils_outil(directive: Directive) -> Seuils:
    methode = directive.quality.min_extraction_method
    methodes = {methode} if isinstance(methode, str) else set(methode)
    return Seuils(min_confiance=directive.quality.min_confidence, methodes=frozenset(methodes))


def _table_alias(directive: Directive) -> dict[tuple[str, str], str]:
    """Table d'alias T6.5 : `(domaine, variante normalisée) → canonique normalisé`."""
    from evidra.memory.envelope import normaliser_label

    table: dict[tuple[str, str], str] = {}
    for domaine, entrees in directive.aliases.items():
        if not isinstance(entrees, dict):
            continue
        for canonique, variantes in entrees.items():
            if not isinstance(variantes, list):
                continue
            for variante in variantes:
                if isinstance(variante, str) and variante.strip():
                    table[(domaine, normaliser_label(variante))] = normaliser_label(canonique)
    return table


def _budgets(directive: Directive) -> Budgets:
    b = directive.budgets
    return Budgets(
        max_tool_calls=b.max_tool_calls,
        max_ingest_per_cycle=b.max_ingest_per_cycle,
        max_cycle_ms=b.max_cycle_ms,
        max_wal_bytes=b.max_wal_bytes,
        reserve_fond=b.reserve_fond,
    )


def demarrer(
    *,
    data_dir: Path,
    directive_path: Path,
    moteur: Any = None,
    outils: Mapping[str, Callable[[], Any]] | None = None,
    horloge: Callable[[], str] | None = None,
    prechauffer: bool = False,
    version_moteur_attendue: str | None = None,
) -> RapportDemarrage:
    """Assemble et démarre : jamais silencieux (degraded motivé ou refus net)."""
    phases: dict[str, dict[str, Any]] = {}
    motifs: list[str] = []
    tic = horloge if horloge is not None else _horloge_defaut

    try:
        directive = charger(directive_path)
    except Exception as exc:
        _LOG.exception("directive illisible : %s", directive_path)
        raise DemarrageError(f"directive : {exc}") from None
    surveillant = Surveillant(directive_path, directive)

    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        magasin = Magasin(data_dir)
    except StoreError as exc:
        raise DemarrageError(f"verrou : {exc}") from None
    try:
        phases["manifeste"] = _phase_manifeste(data_dir, version_moteur_attendue, motifs)
        phases["wal"] = _phase_wal(magasin)
        registres = Registres(magasin)
        phases["registres"] = _phase_registres(registres, tic)
        phases["moteur"] = _phase_moteur(moteur, registres, prechauffer, motifs)
        memoires = _memoires_domaines(magasin, directive)
        total_entites = sum(len(m.entites) for m in memoires.values())
        phases["domaines"] = {
            "domaines": sorted(memoires),
            "entites": total_entites,
            # T6.8 : démarrage à froid = graphe vide ; UNCONFIRMED au jour 0 est normal.
            "demarrage_a_froid": total_entites == 0,
        }
        outil = OutilIngest(
            memoires,
            directive.permissions.en_politique(),
            _seuils_outil(directive),
            tic,
            alias=_table_alias(directive),
        )
        boucle = Boucle(
            domaine=directive.domain,
            ordonnanceur=Scheduler(_budgets(directive)),
            magasin=magasin,
            registres=registres,
            outils=dict(outils or {}),
            surveillant=surveillant,
            horloge=tic,
        )
        phases["boucle"] = {
            "reprise_taches": len([t for t in registres.taches() if t.startswith("task:")])
        }
        _ = outil  # l'outil ingest s'exécute via F1 piloté (tâches T4.4+, pas ici)
        _sceller_manifeste(data_dir, surveillant, magasin)
        degrade = bool(motifs)
        return RapportDemarrage(
            degraded=degrade,
            motifs=tuple(motifs),
            phases=phases,
            boucle=boucle,
            magasin=magasin,
            registres=registres,
            memoires=memoires,
            directive=directive,
            ingest=outil,
        )
    except Exception:
        magasin.close()
        raise


def _phase_manifeste(
    data_dir: Path, version_moteur_attendue: str | None, motifs: list[str]
) -> dict[str, Any]:
    chemin = data_dir / NOM_MANIFASTE
    vmoteur = version_moteur_attendue if version_moteur_attendue is not None else version_moteur()
    if not chemin.exists():
        return {"premier_demarrage": True, "harness": VERSION_SA, "moteur": vmoteur}
    try:
        manifeste = json.loads(chemin.read_text(encoding="utf-8"))
    except ValueError:
        motifs.append("manifeste illisible : poursuite explicite")
        return {"premier_demarrage": False, "degraded": True}
    if manifeste.get("harness") != VERSION_SA:
        motifs.append(f"harness {manifeste.get('harness')} → {VERSION_SA} sous ces données")
    if manifeste.get("moteur") not in (None, vmoteur):
        motifs.append(f"moteur {manifeste.get('moteur')} → {vmoteur} sous ces données")
    return {"premier_demarrage": False, "degraded": bool(motifs), "manifeste": manifeste}


def _phase_wal(magasin: Magasin) -> dict[str, Any]:
    streams = magasin.inventorier()
    total, ignores = 0, 0
    for cle in streams:
        rapport = magasin.flux(cle).relire()
        total += len(rapport.valides)
        ignores += rapport.ignores + rapport.crc_invalides
    return {"streams": streams, "lignes_valides": total, "ignores": ignores}


def _phase_registres(registres: Registres, tic: Callable[[], str]) -> dict[str, Any]:
    abandonnees = registres.relever_expiration(tic())
    return {
        "abandonnees_relevees": abandonnees,
        "taches": len([k for k in registres.taches() if k.startswith("task:")]),
    }


def _phase_moteur(
    moteur: Any, registres: Registres, prechauffer: bool, motifs: list[str]
) -> dict[str, Any]:
    modeles = registres.modeles()
    if modeles:
        motifs.append(
            f"registre modèles non vide ({len(modeles)}) avant B2 levé : rien de consommé"
        )
    rechauffe = False
    if prechauffer and moteur is not None and hasattr(moteur, "analyze_batch"):
        try:
            lancer(lambda: moteur.analyze_batch(["phrase sentinelle."]), 60.0)
            rechauffe = True
        except Exception as exc:  # noqa: BLE001 — préchauffage best-effort, tracé
            _LOG.exception("préchauffage moteur manqué")
            motifs.append(f"préchauffage moteur manqué : {exc}")
    return {
        "modeles_consignes": len(modeles),
        "param_epoch": "non vérifié (I1, amendement en attente)",
        "prechauffe": rechauffe,
        "moteur_fourni": moteur is not None,
    }


def _memoires_domaines(magasin: Magasin, directive: Directive) -> dict[str, Memoire]:
    noms = sorted(
        {cle.split("/")[1] for cle in magasin.inventorier() if cle.startswith("domains/")}
    )
    if directive.domain not in noms:
        noms.append(directive.domain)
    seuils = (directive.quality.seuils_tiers[0], directive.quality.seuils_tiers[1])
    n_confirmee = directive.seuils_provisoires.n_confirmation
    memoires: dict[str, Memoire] = {}
    for nom in noms:
        cle = f"domains/{nom}"
        try:
            charge = magasin.recharger(cle)
        except StoreError:
            charge = None
        if charge is None:
            memoires[nom] = Memoire(nom, seuils, n_confirmee)
        else:
            memoire, _ignores = memoire_depuis_etat(nom, charge.etat, seuils, n_confirmee)
            memoires[nom] = memoire
    return memoires


def _fsync_dossier(dossier: Path) -> None:
    fd = os.open(dossier, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sceller_manifeste(data_dir: Path, surveillant: Surveillant, magasin: Magasin) -> None:
    contenu: dict[str, Any] = {
        "harness": VERSION_SA,
        "directive_hash": surveillant.empreinte_courante(),
        "moteur": version_moteur(),
        "streams": {},
    }
    for cle in magasin.inventorier():
        try:
            seqs = [e.seq for e in magasin.flux(cle).relire().valides]
            contenu["streams"][cle] = max(seqs) if seqs else 0
        except Exception:  # noqa: BLE001 — manifeste best-effort, jamais bloquant
            _LOG.exception("manifeste : stream %s illisible, ignoré", cle)
            continue
    chemin = data_dir / NOM_MANIFASTE
    tmp = chemin.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as flux:
        flux.write(json.dumps(contenu, indent=2, sort_keys=True))
        flux.flush()
        os.fsync(flux.fileno())
    tmp.replace(chemin)
    _fsync_dossier(data_dir)
