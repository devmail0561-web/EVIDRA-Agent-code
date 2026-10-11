"""Conftest SA — rend le moteur importable (PROVISOIRE T0.2).

En attente d'un `uv sync` fonctionnel (bloqué : réseau indisponible pour
télécharger les roues, cf. docs/engine-compat.md), le chemin des sources du
moteur est injecté via la variable d'environnement `GCN_PYTHON_SRC` ou, à
défaut, le chemin relatif vers le workspace moteur voisin.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_MOTEUR_SRC = Path(
    os.environ.get(
        "GCN_PYTHON_SRC",
        Path(__file__).resolve().parent.parent.parent / "projet_CNM" / "gcn-python" / "src",
    )
).resolve()

if str(_MOTEUR_SRC) not in sys.path:
    sys.path.insert(0, str(_MOTEUR_SRC))
