#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Écrivain WAL pour le test de faute `kill -9` (T2.1).

Écrit `--lignes` entrées en ne fsyncant que tous les `--sync-chaque`, en
annonçant chaque sync sur stdout (`SYNC n`, flushé). Le parent tue à -9 puis
vérifie : 0 perte des lignes fsyncées.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from evidra.memory.wal import WAL


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--dossier", required=True)
    args.add_argument("--lignes", type=int, default=60)
    args.add_argument("--sync-chaque", type=int, default=10)
    opts = args.parse_args()
    journal = WAL(Path(opts.dossier) / "wal.jsonl", batch_lignes=10**9, batch_ms=10**9)
    for i in range(1, opts.lignes + 1):
        journal.append("add", f"k{i:04d}", {"n": i})
        if i % opts.sync_chaque == 0:
            journal.sync()
            print(f"SYNC {i}", flush=True)


if __name__ == "__main__":
    main()
