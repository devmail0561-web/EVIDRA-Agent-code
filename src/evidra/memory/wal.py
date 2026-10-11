# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""WAL append-only (T2.1) : un stream = un fichier `wal.jsonl`.

`seq` strictement croissant ; CRC32 sur JSON canonique ; fsync par batch
(seuils **provisoires** et configurables, I9) ; fsync du répertoire à la
création ; verrou `filelock` sur le dossier (une seule instance) ; rejeu
tolérant par ligne (skip + compteurs, jamais d'abort).

Sémantique (§14 de l'étude) : `sync()` après fsync puis `ack()` côté
adaptateur (au-moins-une-fois + dédup idempotente au-dessus) ; `kill -9`
mi-batch ⇒ rejeu sans perte des lignes fsyncées, sans doublon logique.
"""

from __future__ import annotations

import json
import logging
import os
import time
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

log = logging.getLogger("evidra.wal")


class WALError(Exception):
    """WAL inutilisable (verrou pris, dossier illisible, etc.)."""


@dataclass(frozen=True, slots=True)
class Enregistrement:
    """Ligne valide relue : identité + contenu (le CRC est vérifié, non stocké)."""

    seq: int
    ts: str
    op: str
    cle: str
    donnees: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RapportRejeu:
    """Bilan du rejeu : valides + compteurs, jamais d'abort (I12)."""

    valides: tuple[Enregistrement, ...]
    ignores: int
    crc_invalides: int
    trous_seq: int
    tronquee_finale: bool


def _canonique(obj: Mapping[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _crc(charge: bytes) -> str:
    return f"{zlib.crc32(charge) & 0xFFFFFFFF:08x}"


class WAL:
    """Journal append-only d'un stream (verrouillé, fsync par batch)."""

    def __init__(
        self,
        chemin: Path,
        *,
        dossier: Path | None = None,
        batch_lignes: int = 100,
        batch_ms: float = 1000.0,
        delai_verrou: float = 0.0,
        seq_depart: int = 0,
        verrouiller: bool = True,
    ) -> None:
        self._chemin = chemin
        self._dossier = dossier if dossier is not None else chemin.parent
        self._batch_lignes = batch_lignes
        self._batch_ms = batch_ms
        self._verrou: FileLock | None = None
        if verrouiller:
            self._verrou = FileLock(str(self._dossier / "sa.lock"))
            try:
                self._verrou.acquire(timeout=delai_verrou)
            except Timeout:
                raise WALError(f"dossier verrouillé (deux instances ?) : {self._dossier}") from None
        nouveau = not chemin.exists()
        self._dossier.mkdir(parents=True, exist_ok=True)
        self._fichier = open(chemin, "ab")  # noqa: SIM115 — détenu jusqu'à close()
        if nouveau:
            self._fsync_dossier()
        self._seq = max(self._seq_initial(), seq_depart)
        self._tampon = 0
        self._dernier_fsync = time.monotonic()

    def _seq_initial(self) -> int:
        """Reprend au max des `seq` déjà présents (toujours tolérant)."""
        maxi = 0
        try:
            with open(self._chemin, "rb") as flux:
                for brute in flux.read().split(b"\n"):
                    try:
                        seq = int(json.loads(brute.decode("utf-8"))["seq"])
                    except (UnicodeDecodeError, ValueError, KeyError, TypeError):
                        continue
                    maxi = max(maxi, seq)
        except OSError:
            pass
        return maxi

    def close(self) -> None:
        """Flush + fsync final, fermeture, libération du verrou (si détenu)."""
        try:
            self.sync()
        finally:
            self._fichier.close()
            if self._verrou is not None:
                self._verrou.release()

    def __enter__(self) -> WAL:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def append(self, op: str, cle: str, donnees: Mapping[str, Any]) -> int:
        """Ajoute une ligne (`seq` assigné), fsync selon le batch."""
        self._seq += 1
        corps: dict[str, Any] = {
            "seq": self._seq,
            "ts": datetime.now(UTC).isoformat(),
            "op": op,
            "key": cle,
            "data": dict(donnees),
        }
        ligne = _canonique({**corps, "crc": _crc(_canonique(corps))}) + b"\n"
        self._fichier.write(ligne)
        self._tampon += 1
        self._sync_batch()
        return self._seq

    def sync(self) -> None:
        """Flush + fsync immédiats (avant `ack()`, §14)."""
        self._fichier.flush()
        os.fsync(self._fichier.fileno())
        self._tampon = 0
        self._dernier_fsync = time.monotonic()

    def relire(self, *, depuis: int = 0) -> RapportRejeu:
        """Rejoue le fichier : valides + compteurs, dernière ligne tronquée tolérée.

        `depuis` = `last_seq` du snapshot : les lignes antérieures ou égales
        sont déjà pliées (ni valides ni ignorées) ; seuls les trous et
        doublons postérieurs sont comptés.
        """
        self._fichier.flush()
        with open(self._chemin, "rb") as flux:
            lignes = flux.read().split(b"\n")
        if lignes and lignes[-1] == b"":
            lignes.pop()
        valides: list[Enregistrement] = []
        ignores = crc_invalides = trous = 0
        tronquee = False
        maxi = depuis
        for i, brute in enumerate(lignes):
            dernier = i == len(lignes) - 1
            if not brute.strip():
                ignores += 1
                continue
            try:
                objet = json.loads(brute.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                ignores += 1
                tronquee = tronquee or dernier
                log.warning(
                    "wal ligne illisible", extra={"ligne": i + 1, "fichier": str(self._chemin)}
                )
                continue
            if not isinstance(objet, dict):
                ignores += 1
                continue
            crc = objet.pop("crc", None)
            if _crc(_canonique(objet)) != crc:
                crc_invalides += 1
                ignores += 1
                continue
            try:
                seq = int(objet["seq"])
            except (KeyError, TypeError, ValueError):
                ignores += 1
                continue
            if seq <= depuis:
                continue  # déjà plié dans le snapshot, ni valide ni ignoré
            if seq <= maxi:
                ignores += 1  # déjà vu (rejeu idempotent)
                continue
            if seq > maxi + 1:
                trous += seq - maxi - 1
            maxi = seq
            valides.append(
                Enregistrement(
                    seq=seq,
                    ts=str(objet.get("ts", "")),
                    op=str(objet.get("op", "")),
                    cle=str(objet.get("key", "")),
                    donnees=objet.get("data", {}) if isinstance(objet.get("data"), dict) else {},
                )
            )
        self._seq = max(self._seq, maxi)
        return RapportRejeu(
            valides=tuple(valides),
            ignores=ignores,
            crc_invalides=crc_invalides,
            trous_seq=trous,
            tronquee_finale=tronquee,
        )

    def _sync_batch(self) -> None:
        if (
            self._tampon >= self._batch_lignes
            or (time.monotonic() - self._dernier_fsync) * 1000.0 >= self._batch_ms
        ):
            self.sync()

    def _fsync_dossier(self) -> None:
        fd = os.open(self._dossier, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
