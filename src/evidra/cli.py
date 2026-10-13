# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""CLI Evidra (T4.6, `argparse`) : `run` / `ingest` / `query` / `compact` / `status`.

`--data-dir` toujours requis (ADR-0011, pas de défaut implicite).
`--essai` = moteur d'essai NON CALIBRÉ (B1), opt-in explicite dev/dogfood ;
sans moteur, `ingest` refuse net (exit 2). `query`/`compact`/`status`/
`maintenance` fonctionnent sans moteur ; lecture seule sans verrou.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
from pathlib import Path

_LOG = logging.getLogger(__name__)

BUDGET_DEFAUT_LACUNES = 10.0
"""Budget par défaut des tâches P4 créées par `evidra lacunes` ([provisoire], I9)."""


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

    maintenance = sous.add_parser(
        "maintenance", help="candidats STALE + confiance effective (lecture seule)"
    )
    maintenance.add_argument("--data-dir", required=True)
    maintenance.add_argument("--domaine", required=True)
    maintenance.add_argument("--directive", required=False, default=None)
    maintenance.add_argument("--maintenant", required=False, default=None)
    maintenance.set_defaults(fonction=cmd_maintenance)

    arbitrer = sous.add_parser(
        "arbitrer", help="arbitre les paires en conflit (écriture verrouillée)"
    )
    arbitrer.add_argument("--data-dir", required=True)
    arbitrer.add_argument("--domaine", required=True)
    arbitrer.add_argument("--directive", required=True)
    arbitrer.add_argument("--maintenant", required=False, default=None)
    arbitrer.set_defaults(fonction=_cmd_arbitrer)

    aliases = sous.add_parser("aliases", help="table + candidats co-confirmés (lecture seule)")
    aliases.add_argument("--data-dir", required=True)
    aliases.add_argument("--domaine", required=True)
    aliases.add_argument("--directive", required=False, default=None)
    aliases.set_defaults(fonction=cmd_aliases)

    deduire = sous.add_parser("deduire", help="déduction tracée (gate directive, verrouillée)")
    deduire.add_argument("--data-dir", required=True)
    deduire.add_argument("--domaine", required=True)
    deduire.add_argument("--directive", required=True)
    deduire.add_argument("--maintenant", required=False, default=None)
    deduire.set_defaults(fonction=_cmd_deduire)

    lacunes = sous.add_parser("lacunes", help="gaps surveillés → questions → tâches P4 (verrou)")
    lacunes.add_argument("--data-dir", required=True)
    lacunes.add_argument("--domaine", required=True)
    lacunes.add_argument("--directive", required=True)
    lacunes.add_argument("--budget", type=float, default=BUDGET_DEFAUT_LACUNES)
    lacunes.add_argument("--deadline", required=False, default=None)
    lacunes.set_defaults(fonction=_cmd_lacunes)

    serve = sous.add_parser("serve", help="API HTTP : boucle + uvicorn (127.0.0.1 par défaut)")
    serve.add_argument("--directive", required=True)
    serve.add_argument("--data-dir", required=True)
    serve.add_argument(
        "--essai", action="store_true", help="moteur d'essai non calibré (B1, dev uniquement)"
    )
    serve.add_argument("--hote", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(fonction=cmd_serve)

    quarantaine = sous.add_parser(
        "quarantine", help="contenu quarantiné : list (lecture seule) | poser | lever (T9.5)"
    )
    quarantaine.add_argument("action", choices=("list", "poser", "lever"))
    quarantaine.add_argument("--data-dir", required=True)
    quarantaine.add_argument("--domaine", required=True)
    quarantaine.add_argument("--source", required=False, default=None)
    quarantaine.add_argument("--relation", required=False, default=None)
    quarantaine.add_argument("--cible", required=False, default=None)
    quarantaine.add_argument("--motif", required=False, default=None)
    quarantaine.set_defaults(fonction=_cmd_quarantaine)

    purger = sous.add_parser("purger", help="purge les preuves périmées (T9.10, verrouillé)")
    purger.add_argument("--data-dir", required=True)
    purger.add_argument("--domaine", required=True)
    purger.add_argument("--directive", required=False, default=None)
    purger.add_argument("--jours", type=int, required=False, default=None)
    purger.add_argument("--maintenant", required=False, default=None)
    purger.set_defaults(fonction=cmd_purger)

    args = parser.parse_args(argv)
    try:
        return int(args.fonction(args))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:  # noqa: BLE001 — erreur explicite sur stderr, exit 1
        _LOG.exception("échec commande %s", getattr(args, "commande", "?"))
        print(json.dumps({"erreur": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


def _cmd_arbitrer(args: argparse.Namespace) -> int:
    from evidra.arbitrage_cli import cmd_arbitrer

    return cmd_arbitrer(args)


def _cmd_deduire(args: argparse.Namespace) -> int:
    from evidra.arbitrage_cli import cmd_deduire

    return cmd_deduire(args)


def _cmd_lacunes(args: argparse.Namespace) -> int:
    from evidra.arbitrage_cli import cmd_lacunes

    return cmd_lacunes(args)


def _cmd_quarantaine(args: argparse.Namespace) -> int:
    from evidra.quarantine_cli import cmd_quarantaine

    return cmd_quarantaine(args)


def cmd_purger(args: argparse.Namespace) -> int:
    """Purge T9.10 : tombstone des preuves périmées + registre des suppressions."""
    from datetime import UTC, datetime

    from evidra.directive.loader import charger
    from evidra.kernel.contracts import Record
    from evidra.memory.memoire import id_triplet, memoire_depuis_etat
    from evidra.memory.retention import candidates
    from evidra.memory.store import Magasin, StoreError

    jours = args.jours
    if jours is None and args.directive:
        try:
            jours = charger(Path(args.directive)).staleness.retention_jours
        except Exception as exc:
            print(json.dumps({"erreur": f"directive illisible : {exc}"}), file=sys.stderr)
            return 1
    if jours is None:
        print(json.dumps({"purgees": [], "motif": "sans politique de rétention, rien à purger"}))
        return 0
    maintenant = args.maintenant or datetime.now(UTC).isoformat()
    try:
        magasin = Magasin(Path(args.data_dir))
    except StoreError as exc:
        print(json.dumps({"erreur": f"purge impossible : {exc}"}), file=sys.stderr)
        return 1
    try:
        cle = f"domains/{args.domaine}"
        try:
            charge = magasin.recharger(cle)
        except StoreError as exc:
            print(json.dumps({"erreur": str(exc)}), file=sys.stderr)
            return 1
        memo, _ = memoire_depuis_etat(args.domaine, charge.etat)
        ciblees = candidates(memo.entites, maintenant_iso=maintenant, retention_jours=jours)
        purgees = []
        for triplet in ciblees:
            env = memo.entites.get(triplet)
            if env is None:
                continue
            motif = f"rétention dépassée ({jours} j, preuve illisible après purge)"
            magasin.append(
                cle,
                Record(
                    stream=cle,
                    op="tombstone",
                    key=id_triplet(triplet),
                    data={"triplet": list(triplet), "motif": motif},
                ),
            )
            memo.retirer(triplet)
            magasin.append(
                "registry/suppressions",
                Record(
                    stream="registry/suppressions",
                    op="put",
                    key=id_triplet(triplet),
                    data={"triplet": list(triplet), "motif": motif, "date": maintenant},
                ),
            )
            purgees.append(list(triplet))
        print(json.dumps({"domaine": args.domaine, "purgees": purgees}, ensure_ascii=False))
        return 0
    finally:
        magasin.close()


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
    arret = threading.Event()

    def _stop(signum: int, _cadre: object) -> None:
        arret.set()

    # Handlers AVANT le marqueur : `pret` signifie prêt-pour-signaux, sinon un
    # SIGTERM dans la fenêtre tue le processus (disposition par défaut, -15).
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
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
        delai = rapport.directive.budgets.timeout_travailleur_s
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
                timeout_s=delai,
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
    from evidra.memory.store import StoreError, lire_domaine

    try:
        memo, ignores = lire_domaine(Path(args.data_dir), args.domaine)
    except StoreError as exc:
        print(json.dumps({"erreur": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
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
    """État du data_dir : manifeste + rapports par stream, sans verrou (T4.6).

    Tolérant (I12) : manifeste corrompu ⇒ `{}` + avertissement, jamais exit 1 ;
    streams hors clés ⇒ comptés dans `invalides`, jamais crash.
    """
    from evidra.memory.store import etat_racine

    print(json.dumps(etat_racine(Path(args.data_dir)), ensure_ascii=False))
    return 0


def cmd_maintenance(args: argparse.Namespace) -> int:
    """Candidats maintenance P5 : STALE + confiance effective (T6.2, lecture seule)."""
    from datetime import UTC, datetime

    from evidra.directive.loader import charger
    from evidra.directive.schema import Provisoire, Staleness
    from evidra.memory.lifecycle import recenser_stales
    from evidra.memory.store import StoreError, lire_domaine

    try:
        memo, ignores = lire_domaine(Path(args.data_dir), args.domaine)
    except StoreError as exc:
        print(json.dumps({"erreur": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    if args.directive:
        directive = charger(Path(args.directive))
        stale_apres = directive.staleness.stale_after_days
        t_domaine = directive.seuils_provisoires.t_domaine
    else:
        stale_apres = Staleness().stale_after_days
        t_domaine = Provisoire().t_domaine
    maintenant = args.maintenant or datetime.now(UTC).isoformat()
    fiches = recenser_stales(
        memo.entites,
        maintenant_iso=maintenant,
        stale_after_days=stale_apres,
        t_domaine_jours=t_domaine,
    )
    print(
        json.dumps(
            {
                "domaine": args.domaine,
                "maintenant": maintenant,
                "candidats": fiches,
                "ignores_rebuild": ignores,
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_aliases(args: argparse.Namespace) -> int:
    """Alias T6.5 : table promue (directive, humaine) + candidats mûrs (lecture seule)."""
    from evidra.boot.demarrage import _table_alias
    from evidra.directive.loader import charger
    from evidra.memory.store import StoreError, lire_domaine

    try:
        memo, ignores = lire_domaine(Path(args.data_dir), args.domaine)
    except StoreError as exc:
        print(json.dumps({"erreur": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    table: dict = {}
    if args.directive:
        table = _table_alias(charger(Path(args.directive)))
    promus = sorted(
        {"variante": v, "canonique": c} for (d, v), c in table.items() if d == args.domaine
    )
    print(
        json.dumps(
            {
                "domaine": args.domaine,
                "promus": promus,
                "candidats": memo.candidats_alias(table),
                "ignores_rebuild": ignores,
            },
            ensure_ascii=False,
        )
    )
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """API HTTP (T8.6) : démarrage complet + uvicorn (extra `api` requis)."""
    try:
        import uvicorn  # noqa: F401 — extra `api`, jamais en dépendance dure
    except ImportError:
        print(
            json.dumps({"erreur": "extra `api` manquant : uv sync --extra api"}),
            ensure_ascii=False,
            file=sys.stderr,
        )
        return 1
    from evidra.api.app import creer_app
    from evidra.api.auth import autheur_depuis_directive
    from evidra.api.pont import contexte_depuis_rapport
    from evidra.boot.demarrage import demarrer

    moteur = _moteur_essai_ou_rien(args.essai)
    rapport = demarrer(
        data_dir=Path(args.data_dir),
        directive_path=Path(args.directive),
        moteur=moteur,
    )
    if rapport.boucle is None:
        print(json.dumps({"erreur": "boucle indisponible"}), file=sys.stderr)
        return 1
    ctx = contexte_depuis_rapport(rapport, Path(args.data_dir), moteur=moteur)
    if ctx is None:
        print(json.dumps({"erreur": "contexte API indisponible"}), file=sys.stderr)
        return 1
    autheur = autheur_depuis_directive(rapport.directive) if rapport.directive else None
    app = creer_app(rapport.boucle, ctx, autheur=autheur, directive_path=Path(args.directive))
    uvicorn.run(app, host=args.hote, port=args.port)
    return 0
