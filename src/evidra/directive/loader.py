# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Chargement de directive (T4.2) : fichier → `Directive` validée ou `DirectiveError`.

`charger()` ne devine jamais : fichier manquant, JSON illisible ou schéma
invalide ⇒ `DirectiveError` précis (chemin du champ, T4.1). L'ancienne
directive reste en vigueur (rejet + alerte, jamais de poursuite aveugle).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evidra.directive.schema import Directive, valider
from evidra.logging import DirectiveError


def empreinte_fichier(chemin: Path) -> tuple[int, str]:
    """`(mtime_ns, sha256)` : mtime d'abord, hash ensuite (T4.2)."""
    mtime = chemin.stat().st_mtime_ns
    return mtime, hashlib.sha256(chemin.read_bytes()).hexdigest()


def charger(chemin: Path) -> Directive:
    """Lit et valide une directive (fail-closed, motif précis)."""
    try:
        brut = chemin.read_text(encoding="utf-8")
    except OSError:
        raise DirectiveError(f"directive introuvable ou illisible : {chemin}") from None
    try:
        donnees: Any = json.loads(brut)
    except ValueError:
        raise DirectiveError(f"directive JSON illisible : {chemin}") from None
    return valider(donnees)
