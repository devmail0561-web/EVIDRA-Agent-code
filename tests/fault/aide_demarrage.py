#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Aide crash-test T4.5 : démarre, ingère, crée une tâche, sync, puis MEURT.

`os._exit` (pas de close) : simule `kill -9` — verrou abandonné, tampons
perdus, fsyncs tenus. Le parent vérifie la reprise à l'identique.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from evidra.boot.demarrage import demarrer
from evidra.kernel.contracts import Context
from evidra.memory.envelope import CirCore, Provenance


def _noyau(ref: str) -> CirCore:
    return CirCore(
        source="Authentification",
        target="accès",
        relation="cause",
        confidence=0.87,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="gcn-core-4.0.0",
            extracted_at="t",
        ),
    )


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--data-dir", required=True)
    args.add_argument("--directive", required=True)
    opts = args.parse_args()
    rapport = demarrer(data_dir=Path(opts.data_dir), directive_path=Path(opts.directive))
    assert (
        rapport.ingest is not None and rapport.magasin is not None and rapport.registres is not None
    )
    ctx = Context(store=rapport.magasin, domain="code")
    rapport.ingest.run(ctx, {"noyaux": [_noyau("doc://1"), _noyau("doc://2")], "channel": "test"})
    rapport.registres.creer_tache("k1", "essai", 5.0, "2030-01-01T00:00:00+00:00")
    rapport.magasin.synchroniser()
    os._exit(7)


if __name__ == "__main__":
    main()
