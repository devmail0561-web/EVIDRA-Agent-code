# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Adaptateur `local_files` (T3.7) : fichiers → `RawDoc`, 100 % offline.

`poll(since)` par `mtime_ns` + taille + sha256 (re-hash si mtime/taille
bougent) ; `glob` configurables, polling stdlib (pas de dépendance) ; curseur
opaque JSON persisté par l'appelant (registres, T2.6) via `curseur()`, marqué
via `ack()` ; lecture STRICTEMENT seule (ADR-0011 : aucun fichier SA à côté
des sources — ni verrou, ni sidecar) ; cachés (`.git`, `.venv`, …) et
`__pycache__` exclus ; non-texte sauté (journalisé).

Ancrage (T3.2) : `etendue()` donne l'ancre document — `TokenSpan(0, len)` en
texte, `CodeSpan` fichier entier en code. Grossier mais vrai et vérifiable
(re-hash) ; l'affinage au mot exige la lattice moteur (T5.4).
`requires_network = False` (dogfood offline, I10).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidra.kernel.contracts import CostHint, Cursor, RawDoc
from evidra.memory.envelope import CodeSpan, Span, TokenSpan

log = logging.getLogger("evidra.adapters.local_files")

MIMES = {".txt": "text/plain", ".md": "text/markdown", ".py": "text/x-python"}
"""Types lus en texte (vocabulaire de l'adaptateur, le reste est sauté)."""

EXCLUS = frozenset(
    {
        ".git",
        ".venv",
        ".hg",
        ".svn",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
    }
)
"""Caches VCS/outils jamais ingérés (politique de l'adaptateur ; de toute façon,
tout segment caché `.*` est exclu par `_est_exclu`)."""


def _est_exclu(chemin: Path, racine: Path) -> bool:
    try:
        relatif = chemin.relative_to(racine)
    except ValueError:
        return True
    return any(partie in EXCLUS or partie.startswith(".") for partie in relatif.parts)


def _meta(chemin: Path) -> dict[str, Any] | None:
    try:
        st = chemin.stat()
        return {"mtime_ns": st.st_mtime_ns, "taille": st.st_size}
    except OSError:
        return None


def _sha(chemin: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(chemin, "rb") as flux:
            for bloc in iter(lambda: flux.read(65536), b""):
                h.update(bloc)
        return h.hexdigest()
    except OSError:
        return None


class AdaptateurFichiers:
    """Adapte un dossier source (lecture seule) au contrat `Adapter`."""

    name = "local_files"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"since": {"type": ["string", "null"]}},
    }
    output_schema: Mapping[str, Any] = {"type": "object", "properties": {"docs": {"type": "array"}}}
    cost_hint = CostHint(ms=10.0, calls=1)
    permissions: frozenset = frozenset()  # aucun besoin harness (lecture OS seule)
    channels: tuple[str, ...] = ("local_files",)
    requires_network = False

    def __init__(
        self,
        racine: Path | str,
        *,
        motifs: tuple[str, ...] = ("**/*.md", "**/*.py", "**/*.txt"),
        canal: str = "local_files",
    ) -> None:
        self._racine = Path(racine)
        self._motifs = motifs
        self.canal = canal
        self._etat: dict[str, dict[str, Any]] = {}
        self._dernier_ack: str | None = None

    def poll(self, since: Cursor | None) -> list[RawDoc]:
        """Scanne et retourne les documents nouveaux/modifiés (triés)."""
        if not self._racine.is_dir():
            raise ValueError(f"racine illisible : {self._racine}")
        racine = self._racine.resolve()
        vus = self._charger_curseur(since)
        trouves: list[RawDoc] = []
        for motif in self._motifs:
            for chemin in sorted(self._racine.glob(motif)):
                try:
                    reel = chemin.resolve()
                except (OSError, RuntimeError):
                    continue
                if not reel.is_relative_to(racine):
                    log.debug("hors racine sauté", extra={"fichier": str(chemin)})
                    continue
                if not chemin.is_file() or _est_exclu(chemin, self._racine):
                    continue
                meta = _meta(chemin)
                if meta is None:
                    continue
                cle = str(chemin.relative_to(self._racine))
                ancien = vus.get(cle)
                sha = ancien.get("sha") if isinstance(ancien, dict) else None
                if (
                    isinstance(ancien, dict)
                    and ancien.get("mtime_ns") == meta["mtime_ns"]
                    and ancien.get("taille") == meta["taille"]
                    and sha
                ):
                    self._etat[cle] = ancien
                    continue
                sha = _sha(chemin)
                if sha is None:
                    continue
                if isinstance(ancien, dict) and ancien.get("sha") == sha:
                    self._etat[cle] = {
                        "mtime_ns": meta["mtime_ns"],
                        "taille": meta["taille"],
                        "sha": sha,
                    }
                    continue
                texte = self._lire_texte(chemin)
                self._etat[cle] = {
                    "mtime_ns": meta["mtime_ns"],
                    "taille": meta["taille"],
                    "sha": sha,
                }
                if texte is None:
                    continue
                trouves.append(
                    RawDoc(
                        uri=chemin.absolute().as_uri(),
                        text=texte,
                        channel=self.canal,
                        mime=MIMES.get(chemin.suffix.lower(), "text/plain"),
                        published_at=datetime.fromtimestamp(
                            meta["mtime_ns"] / 1e9, UTC
                        ).isoformat(),
                    )
                )
        return trouves

    def ack(self, curseur: str) -> None:
        """Marque un curseur (validé, fail-fast) ; la persistance relève de l'appelant."""
        try:
            objet = json.loads(curseur)
        except ValueError:
            raise ValueError("curseur illisible") from None
        if not isinstance(objet, dict) or not isinstance(objet.get("vus"), dict):
            raise ValueError("curseur mal formé")
        self._dernier_ack = curseur

    def curseur(self) -> str:
        """État courant sérialisé (à persister via les registres, T2.6)."""
        return json.dumps({"vus": self._etat}, sort_keys=True)

    def etendue(self, texte: str, *, code: bool = False, fichier: str = "") -> Span:
        """Ancre document : `TokenSpan` couvrant ou `CodeSpan` fichier entier."""
        if code:
            lignes = texte.count("\n") + (0 if texte.endswith("\n") or not texte else 1)
            return CodeSpan(fichier, 1, max(1, lignes))
        return TokenSpan(0, len(texte))

    def _charger_curseur(self, curseur: str | None) -> dict[str, Any]:
        if curseur is None:
            return {}
        try:
            objet = json.loads(curseur)
        except ValueError:
            log.warning("curseur illisible : re-scan complet (idempotent)")
            return {}
        vus = objet.get("vus") if isinstance(objet, dict) else None
        return dict(vus) if isinstance(vus, dict) else {}

    def _lire_texte(self, chemin: Path) -> str | None:
        try:
            return chemin.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, ValueError):
            log.debug("non-texte sauté", extra={"fichier": str(chemin)})
            return None
