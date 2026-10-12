# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""CLI Evidra (T4.6, `argparse`) : `run` / `ingest` / `query` / `compact` / `status`.

`--data-dir` toujours requis (ADR-0011, pas de défaut implicite).
`--essai` = moteur d'essai NON CALIBRÉ (B1), opt-in explicite dev/dogfood ;
sans moteur, `ingest` refuse net (exit 2). `query`/`compact`/`status`
fonctionnent sans moteur ; `status` ne verrouille jamais (lecture seule).
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    """Point d'entrée `evidra` : dispatch, 0 ok / 1 erreur / 2 refus d'ingest."""
    parser = argparse.ArgumentParser(prog="evidra", description="Agent causal Evidra (SA)")
    sous = parser.add_subparsers(dest="commande", required=True)

    run = sous.add_parser("run", help="démarre la boucle (dogfood)")
    run.add_argument("--directive", required=True)
    run.add_argument("--data-dir", required=True)
    run.add_argument(
        "--essai", action="store_true", help="moteur d'essai non calibré (B1, dev uniquement)"
    )
    run.set_defaults(fonction=cmd_run)

    ingest = sous.add_parser("ingest", help="ingère un fichier ou dossier")
    ingest.add_argument("chemin")
    ingest.add_argument("--directive", required=True)
    ingest.add_argument("--data-dir", required=True)
    ingest.add_argument(
        "--essai", action="store_true", help="moteur d'essai non calibré (B1, dev uniquement)"
    )
    ingest.set_defaults(fonction=cmd_ingest)

    query = sous.add_parser("query", help="causes|effects d'un concept (avec provenance)")
    query.add_argument("sens", choices=("causes", "effects"))
    query.add_argument("concept")
    query.add_argument("--data-dir", required=True)
    query.add_argument("--domaine", required=True)
    query.set_defaults(fonction=cmd_query)

    compact = sous.add_parser("compact", help="compacte les streams d'un domaine")
    compact.add_argument("--data-dir", required=True)
    compact.add_argument("--domaine", required=True)
    compact.set_defaults(fonction=cmd_compact)

    status = sous.add_parser("status", help="état du data_dir (lecture seule, sans verrou)")
    status.add_argument("--data-dir", required=True)
    status.set_defaults(fonction=cmd_status)

    args = parser.parse_args(argv)
    try:
        return int(args.fonction(args))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001 — erreur explicite sur stderr, exit 1
        print(json.dumps({"erreur": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


def _moteur_essai_ou_rien(essai: bool):
    if not essai:
        return None
    from evidra.engine_bridge.binaire import trouver_binaire
    from evidra.engine_bridge.essai import moteur_essai

    moteur, _reelle = moteur_essai(trouver_binaire())
    return moteur


def cmd_run(args: argparse.Namespace) -> int:
    """Démarre la boucle ; SIGINT/SIGTERM ⇒ reçu final, fsync, verrou libéré (T4.7)."""
    from evidra.boot.demarrage import demarrer
    from evidra.kernel.contracts import Record

    rapport = demarrer(
        data_dir=Path(args.data_dir),
        directive_path=Path(args.directive),
        moteur=_moteur_essai_ou_rien(args.essai),
    )
    boucle = rapport.boucle
    assert boucle is not None and rapport.magasin is not None
    print(
        json.dumps(
            {
                "pret": True,
                "domaine": rapport.directive.domain if rapport.directive else "",
                "degraded": rapport.degraded,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    arret = threading.Event()

    def _stop(signum: int, _cadre: object) -> None:
        arret.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        boucle.boucler(arret)
    finally:
        flux = f"domains/{boucle.domaine}"
        rapport.magasin.append(
            flux,
            Record(
                stream=flux,
                op="receipt",
                key=f"arret:{boucle.compteur}",
                data={"sorte": "arret", "tick": boucle.compteur},
            ),
        )
        rapport.magasin.close()
    print(json.dumps({"arrete": True, "ticks": boucle.compteur}, ensure_ascii=False))
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Ingère un fichier/dossier ; sans moteur : refus net (exit 2, B2)."""
    from evidra.adapters.local_files import AdaptateurFichiers
    from evidra.boot.demarrage import demarrer
    from evidra.ingestion import traiter_document
    from evidra.kernel.contracts import Context

    moteur = _moteur_essai_ou_rien(args.essai)
    if moteur is None:
        print(
            json.dumps(
                {"erreur": "extraction indisponible sans moteur (B2 ; --essai pour le dev)"},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    rapport = demarrer(
        data_dir=Path(args.data_dir), directive_path=Path(args.directive), moteur=moteur
    )
    assert (
        rapport.magasin is not None and rapport.ingest is not None and rapport.directive is not None
    )
    try:
        chemin = Path(args.chemin)
        if chemin.is_file():
            adaptateur = AdaptateurFichiers(chemin.parent, motifs=(chemin.name,))
        else:
            adaptateur = AdaptateurFichiers(chemin)
        ctx = Context(store=rapport.magasin, domain=rapport.directive.domain)
        total = {"documents": 0, "ajoutees": 0, "confirmees": 0}
        for doc in adaptateur.poll(None):
            stats = traiter_document(
                adaptateur=adaptateur,
                moteur=moteur,
                outil=rapport.ingest,
                ctx=ctx,
                uri=doc.uri,
                texte=doc.text,
                code=doc.uri.endswith(".py"),
                fichier=doc.uri,
            )
            total["documents"] += 1
            total["ajoutees"] += stats["ajoutees"]
            total["confirmees"] += stats["confirmees"]
        print(json.dumps(total, ensure_ascii=False))
        return 0
    finally:
        rapport.magasin.close()


def cmd_query(args: argparse.Namespace) -> int:
    """Requête causes/effects avec provenance (sans moteur, sans verrou)."""
    from evidra.memory.memoire import appliquer_domaine, memoire_depuis_etat
    from evidra.memory.snapshot import charger
    from evidra.memory.wal import WAL

    dossier = Path(args.data_dir) / "domains" / args.domaine
    if not dossier.is_dir():
        print(
            json.dumps({"erreur": f"domaine inconnu : {args.domaine}"}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    with WAL(dossier / "wal.jsonl", verrouiller=False) as journal:
        charge = charger(dossier, journal, appliquer=appliquer_domaine)
    memo, ignores = memoire_depuis_etat(args.domaine, charge.etat)
    sorties = []
    for triplet, env in sorted(memo.entites.items()):
        ids = (
            memo.index.causes(env.cir.target)
            if args.sens == "causes"
            else memo.index.effets(env.cir.source)
        )
        if not ids:
            continue
        cible = env.cir.target if args.sens == "causes" else env.cir.source
        if args.concept.lower() not in cible.lower() and cible.lower() not in args.concept.lower():
            continue
        sorties.append(
            {
                "concept": cible,
                "preuves": len(ids),
                "ref": env.cir.provenance.ref,
                "confiance": env.cir.confidence,
                "triplet": list(triplet),
            }
        )
    print(
        json.dumps(
            {
                "sens": args.sens,
                "concept": args.concept,
                "reponses": sorties,
                "ignores_rebuild": ignores,
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_compact(args: argparse.Namespace) -> int:
    """Snapshot + troncation des streams du domaine (verrou requis : refuse si l'agent tourne)."""
    from evidra.memory.store import Magasin

    try:
        magasin = Magasin(Path(args.data_dir))
    except Exception as exc:
        print(
            json.dumps({"erreur": f"compactage impossible : {exc}"}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    try:
        resultats = {}
        cible = f"domains/{args.domaine}"
        for cle in magasin.inventorier():
            if cle == cible:
                magasin.snapshot(cle)
                resultats[cle] = "compacte"
        print(json.dumps({"domaine": args.domaine, "streams": resultats}, ensure_ascii=False))
        return 0
    finally:
        magasin.close()


def cmd_status(args: argparse.Namespace) -> int:
    """État du data_dir : manifeste + rapports par stream, sans verrou (T4.6)."""
    from evidra.memory.memoire import appliquer_domaine
    from evidra.memory.snapshot import charger
    from evidra.memory.wal import WAL

    racine = Path(args.data_dir)
    manifeste = {}
    chemin_manifeste = racine / "sa_manifest.json"
    if chemin_manifeste.exists():
        manifeste = json.loads(chemin_manifeste.read_text(encoding="utf-8"))
    streams = []
    for wal in sorted(racine.rglob("wal.jsonl")):
        dossier = wal.parent
        try:
            cle = str(dossier.relative_to(racine)).replace("\\", "/")
        except ValueError:
            continue
        with WAL(wal, verrouiller=False) as journal:
            charge = charger(dossier, journal, appliquer=appliquer_domaine, stream=cle)
        streams.append(charge.rapport.en_dict() if charge.rapport is not None else {"stream": cle})
    print(json.dumps({"manifeste": manifeste, "streams": streams}, ensure_ascii=False))
    return 0
