# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Snapshot et compaction (T2.2) : `snapshot.json` + `.prev` + `wal.jsonl`.

Écriture tmp → fsync → rename atomique ; l'ancien snapshot est conservé en
`.prev`. Chargement = snapshot + rejeu des `seq > last_seq` (jamais de
re-snapshot systématique qui masquerait une corruption) ; snapshot corrompu
ou version inconnue ⇒ repli `.prev` + rejeu plus long, signalé. Les
tombstones se rejouent sans forcer de snapshot.

Injection de fautes (test uniquement) : `panne_apres` lève `PanneSimulee`
après l'étape nommée (`tmp`, `prev`, `rename`, `troncation`) — l'état
rechargé doit rester identique à chaque étape.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evidra.memory.wal import WAL, Enregistrement, RapportRejeu

VERSION_SNAPSHOT = 1

NOM_SNAPSHOT = "snapshot.json"
NOM_PREV = "snapshot.json.prev"
NOM_TMP = "snapshot.json.tmp"
NOM_WAL = "wal.jsonl"


class PanneSimulee(Exception):  # noqa: N818 — vocabulaire du plan (étape de compaction)
    """Incident simulé après une étape de compaction (test uniquement)."""


def sous_dossier(racine: Path, *parties: str) -> Path:
    """Construit un sous-chemin confiné sous `racine` (ADR-0011).

    Refuse `..`, segments vides, séparateurs et chemins absolus : aucun
    fichier d'état SA ne peut s'écrire hors de la racine explicite
    (`--data-dir`, jamais de défaut implicite). Le Store (T2.4) est le seul
    à construire les dossiers de streams, toujours via cette fonction.
    """
    if not parties:
        raise ValueError("au moins un segment exigé")
    for partie in parties:
        if not partie or partie in (".", ".."):
            raise ValueError(f"segment interdit : {partie!r}")
        if Path(partie).is_absolute() or "/" in partie or "\\" in partie:
            raise ValueError(f"segment interdit : {partie!r} (portable uniquement)")
    racine_abs = racine.resolve()
    candidat = racine.joinpath(*parties).resolve()
    if candidat != racine_abs and not str(candidat).startswith(str(racine_abs) + os.sep):
        raise ValueError(f"évasion hors racine : {candidat}")
    return racine.joinpath(*parties)


@dataclass(frozen=True, slots=True)
class Chargement:
    """État rechargé : snapshot + WAL rejoué par l'appelant (`appliquer`)."""

    etat: dict[str, Any]
    last_seq: int
    source: str  # "snapshot" | "prev" | "vide"
    avertissements: tuple[str, ...]
    rejouees: int
    rejeu: RapportRejeu
    rapport: LoadReport | None = None  # T2.7 : consommé par le démarrage (T4.5)


@dataclass(frozen=True, slots=True)
class LoadReport:
    """Rapport de chargement d'un stream (T2.7) : phase 2 du démarrage (T4.5)."""

    stream: str
    snapshot_loaded: bool
    source: str
    replayed: int
    skipped: int
    crc_failed: int
    seq_gaps: int
    duration_ms: float

    def en_dict(self) -> dict[str, Any]:
        """Rendu JSON pour le rapport de démarrage."""
        return {
            "stream": self.stream,
            "snapshot_loaded": self.snapshot_loaded,
            "source": self.source,
            "replayed": self.replayed,
            "skipped": self.skipped,
            "crc_failed": self.crc_failed,
            "seq_gaps": self.seq_gaps,
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass(frozen=True, slots=True)
class RapportCompaction:
    """Bilan : effectuée ou non (seuil), `last_seq` scellé."""

    effectuee: bool
    last_seq: int


def _canon(objet: Mapping[str, Any]) -> bytes:
    return json.dumps(objet, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )


def _fsync_dossier(dossier: Path) -> None:
    fd = os.open(dossier, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def ecrire_snapshot(
    dossier: Path, etat: Mapping[str, Any], last_seq: int, *, version: int = VERSION_SNAPSHOT
) -> None:
    """Scelle `etat` : tmp → fsync → prev → rename → fsync dossier."""
    _etapes(dossier, etat, last_seq, version=version, panne_apres=None)


def _etapes(
    dossier: Path, etat: Mapping[str, Any], last_seq: int, *, version: int, panne_apres: str | None
) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    tmp, snap, prev = dossier / NOM_TMP, dossier / NOM_SNAPSHOT, dossier / NOM_PREV
    with open(tmp, "wb") as flux:
        flux.write(_canon({"version": version, "last_seq": last_seq, "state": dict(etat)}) + b"\n")
        flux.flush()
        os.fsync(flux.fileno())
    if panne_apres == "tmp":
        raise PanneSimulee("tmp")
    if snap.exists():
        os.replace(snap, prev)
    if panne_apres == "prev":
        raise PanneSimulee("prev")
    os.replace(tmp, snap)
    _fsync_dossier(dossier)
    if panne_apres == "rename":
        raise PanneSimulee("rename")


def _lire_photo(chemin: Path) -> tuple[dict[str, Any], int] | None:
    try:
        objet = json.loads(chemin.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(objet, dict) or objet.get("version") != VERSION_SNAPSHOT:
        return None
    try:
        last_seq = int(objet["last_seq"])
    except (KeyError, TypeError, ValueError):
        return None
    etat = objet.get("state")
    if not isinstance(etat, dict):
        return None
    import copy

    return copy.deepcopy(etat), last_seq


def charger(
    dossier: Path,
    journal: WAL,
    *,
    appliquer: Callable[[dict[str, Any], Enregistrement], None],
    stream: str = "",
) -> Chargement:
    """Snapshot (ou `.prev`, ou vide) + rejeu des `seq > last_seq`."""
    debut = time.monotonic()
    avertissements: list[str] = []
    photo = _lire_photo(dossier / NOM_SNAPSHOT)
    source = "snapshot"
    if photo is None:
        avertissements.append("snapshot illisible ou version inconnue")
        photo = _lire_photo(dossier / NOM_PREV)
        source = "prev"
    if photo is None:
        avertissements.append("repli : démarrage vide")
        photo = ({}, 0)
        source = "vide"
    etat, last_seq = photo
    rejeu = journal.relire(depuis=last_seq)
    rejouees = 0
    for enr in rejeu.valides:
        if enr.seq > last_seq:
            appliquer(etat, enr)
            last_seq = enr.seq
            rejouees += 1
    rapport = LoadReport(
        stream=stream,
        snapshot_loaded=source != "vide",
        source=source,
        replayed=rejouees,
        skipped=rejeu.ignores,
        crc_failed=rejeu.crc_invalides,
        seq_gaps=rejeu.trous_seq,
        duration_ms=(time.monotonic() - debut) * 1000.0,
    )
    return Chargement(
        etat=etat,
        last_seq=last_seq,
        source=source,
        avertissements=tuple(avertissements),
        rejouees=rejouees,
        rejeu=rejeu,
        rapport=rapport,
    )


def compacter(
    dossier: Path,
    journal: WAL,
    etat: Mapping[str, Any],
    last_seq: int,
    *,
    seuil_octets: int | None = None,
    panne_apres: str | None = None,
    version: int = VERSION_SNAPSHOT,
) -> RapportCompaction:
    """Plie l'état courant dans le snapshot puis tronque le WAL.

    `seuil_octets` : sous le seuil, ne rien faire (`effectuee=False`).
    """
    if panne_apres not in (None, "tmp", "prev", "rename", "troncation"):
        raise ValueError(f"étape inconnue : {panne_apres!r}")
    wal = dossier / NOM_WAL
    if seuil_octets is not None and (not wal.exists() or wal.stat().st_size < seuil_octets):
        return RapportCompaction(effectuee=False, last_seq=last_seq)
    _etapes(dossier, etat, last_seq, version=version, panne_apres=panne_apres)
    if panne_apres == "troncation":
        raise PanneSimulee("troncation")
    with open(wal, "wb") as flux:
        flux.flush()
        os.fsync(flux.fileno())
    _fsync_dossier(dossier)
    journal.sync()
    return RapportCompaction(effectuee=True, last_seq=last_seq)
