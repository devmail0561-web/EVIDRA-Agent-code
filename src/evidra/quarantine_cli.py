# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Quarantaine contenu (T9.5) : `list` (lecture seule) / `poser` / `lever` (verrou).

Stockée (traçabilité), exclue des requêtes et des `CONFIRMED` (`Memoire.preuves`,
outil `validate`), visible en audit. Sortie par arbitrage humain (`lever`) ou
corroboration indépendante non-agent (auto, T9.3). Écriture WAL `quarantine`
(capsule complète, rejouée par `appliquer_domaine`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evidra.kernel.contracts import Record
from evidra.memory.envelope import resume
from evidra.memory.memoire import id_triplet, memoire_depuis_etat
from evidra.memory.store import Magasin, StoreError, lire_domaine


def cmd_quarantaine(args: argparse.Namespace) -> int:
    """Dispatch `list | poser | lever` (T9.5)."""
    action = getattr(args, "action", "list")
    if action == "list":
        return _lister(args)
    if action in ("poser", "lever"):
        return _muter(args, poser=action == "poser")
    print(
        json.dumps({"erreur": f"action inconnue : {action!r}"}, ensure_ascii=False),
        file=sys.stderr,
    )
    return 1


def _lister(args: argparse.Namespace) -> int:
    try:
        memo, ignores = lire_domaine(Path(args.data_dir), args.domaine)
    except StoreError as exc:
        print(json.dumps({"erreur": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    items = [
        {
            "triplet": list(triplet),
            "motif": env.quarantine,
            "statut": env.status.value,
            "canal": env.ingest_channel,
        }
        for triplet, env in sorted(memo.entites.items())
        if env.quarantine is not None
    ]
    print(
        json.dumps(
            {"domaine": args.domaine, "quarantaine": items, "ignores_rebuild": ignores},
            ensure_ascii=False,
        )
    )
    return 0


def _muter(args: argparse.Namespace, *, poser: bool) -> int:
    try:
        triplet = (args.domaine, args.source, args.relation, args.cible)
    except AttributeError:
        print(
            json.dumps({"erreur": "poser/lever exigent --source --relation --cible"}),
            file=sys.stderr,
        )
        return 1
    motif = getattr(args, "motif", None) if poser else None
    if poser and (not isinstance(motif, str) or not motif.strip()):
        print(json.dumps({"erreur": "motif non vide exigé"}), file=sys.stderr)
        return 1
    try:
        magasin = Magasin(Path(args.data_dir))
    except StoreError as exc:
        print(json.dumps({"erreur": f"quarantaine impossible : {exc}"}), file=sys.stderr)
        return 1
    try:
        cle = f"domains/{args.domaine}"
        try:
            charge = magasin.recharger(cle)
        except StoreError as exc:
            print(json.dumps({"erreur": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1
        memo, _ = memoire_depuis_etat(args.domaine, charge.etat)
        ok, message = memo.mettre_quarantaine(triplet, motif.strip() if poser else None)
        if not ok:
            print(json.dumps({"erreur": message}, ensure_ascii=False), file=sys.stderr)
            return 1
        env = memo.entites[triplet]
        magasin.append(
            cle,
            Record(
                stream=cle,
                op="quarantine",
                key=id_triplet(triplet),
                data={
                    "triplet": list(triplet),
                    "observation": "",
                    "enveloppe": dict(resume(env)),
                },
            ),
        )
        print(
            json.dumps(
                {"domaine": args.domaine, "triplet": list(triplet), "resultat": message},
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        magasin.close()
