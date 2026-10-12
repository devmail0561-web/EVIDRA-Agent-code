# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Résolution du binaire `gcn` (lattice Rust) : `GCN_BIN`, PATH, ou défaut dev.

`None` si introuvable — l'appelant bascule sur parseur stub (plumbing) ou
échoue explicitement (dogfood réel). Jamais de téléchargement implicite.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_DEFAUT_DEV = (
    Path(__file__).resolve().parent.parent.parent.parent
    / ".."
    / "projet_CNM"
    / "gcn-core"
    / "target"
    / "release"
    / "gcn"
)


def trouver_binaire() -> str | None:
    """Chemin du binaire `gcn`, ou `None` (appelant : stub ou fail-closed)."""
    env = os.environ.get("GCN_BIN")
    if env and Path(env).is_file():
        return env
    lequel = shutil.which("gcn")
    if lequel:
        return lequel
    if _DEFAUT_DEV.is_file():
        return str(_DEFAUT_DEV)
    return None
