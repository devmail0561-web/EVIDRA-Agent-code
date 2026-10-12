#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Charge 72 h (T7.4) : boucle en continu, mesure ticks/s et dérive mémoire.

Protocole : `python scripts/charge_72h.py --data-dir D --directive J
--duree-s 259200` (défaut 72 h). Sortie JSON : ticks, ticks/s, entités,
alertes levées. CI : ne jamais lancer 72 h ; fumer avec `--duree-s 2`.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import tracemalloc
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

from evidra.boot.demarrage import demarrer  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Charge longue : boucle + mesures")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--directive", required=True)
    parser.add_argument("--duree-s", type=float, default=72 * 3600.0)
    args = parser.parse_args()
    if args.duree_s <= 0:
        print(json.dumps({"erreur": "duree-s > 0 exigée"}))
        return 2
    rapport = demarrer(data_dir=Path(args.data_dir), directive_path=Path(args.directive))
    assert rapport.boucle is not None and rapport.magasin is not None
    tracemalloc.start()
    arret = threading.Event()
    debut = time.monotonic()
    try:
        fil = threading.Thread(target=rapport.boucle.boucler, args=(arret,), daemon=True)
        fil.start()
        time.sleep(args.duree_s)
    finally:
        arret.set()
    duree = time.monotonic() - debut
    courant, pic = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    ticks = rapport.boucle.compteur
    print(
        json.dumps(
            {
                "ticks": ticks,
                "ticks_s": ticks / duree if duree > 0 else 0.0,
                "duree_s": duree,
                "entites": sum(len(m.entites) for m in rapport.memoires.values()),
                "memoire_courante_o": courant,
                "memoire_pic_o": pic,
            }
        )
    )
    rapport.magasin.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
