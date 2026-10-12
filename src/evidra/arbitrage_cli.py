# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Arbitrage CLI (T6.4) : paires en conflit → MAINTENUE / INVALIDEE / révision.

Verrou `Magasin` requis (comme `compact`) : refuse si l'agent tourne.
Séparé de `cli.py` pour garder le dispatch lisible ; importé paresseusement.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidra.directive.loader import charger
from evidra.kernel.contracts import Record, Status
from evidra.memory.arbitration import decider, score_produit
from evidra.memory.envelope import Statut, resume
from evidra.memory.lifecycle import fraicheur
from evidra.memory.memoire import Memoire, id_triplet, memoire_depuis_etat
from evidra.memory.sources import Compteurs, SeuilsSources, fiabilite
from evidra.memory.store import Magasin, StoreError


def seuils_sources_directive(directive: Any) -> SeuilsSources:
    """Seuils effectifs depuis `seuils_provisoires` (source unique : schéma)."""
    prov = directive.seuils_provisoires
    return SeuilsSources(
        poids_confirmation=prov.poids_confirmation,
        n_min=prov.n_min_source,
        seuil_confiance=prov.seuil_confiance_source,
        plafond_contradiction=prov.plafond_contradiction,
        seuil_suspect=prov.seuil_suspect,
        plancher_surveillee=prov.plancher_surveillee,
    )


def score_bord(
    memo: Memoire,
    triplet: tuple[str, str, str, str],
    magasin: Magasin,
    seuils: SeuilsSources,
    t_domaine: float,
    nmax: float | int,
    maintenant: str,
) -> float:
    """Score composite §6.9 (fiabilité = registre source, jamais moteur)."""
    env = memo.entites[triplet]
    trouve = magasin.lookup("registry/sources", env.cir.provenance.ref)
    brut = trouve.data.get("compteurs") if trouve is not None else None
    fiab, _ = fiabilite(Compteurs.depuis_dict(brut), seuils)
    frais, _ = fraicheur(
        env.cir.provenance.published_at,
        maintenant_iso=maintenant,
        t_domaine_jours=t_domaine,
    )
    return score_produit(env.cir.confidence, fiab, env.confirmation_count, frais, nmax=nmax)


def appliquer_verdict(
    magasin: Magasin,
    memo: Memoire,
    cle: str,
    t_gagnant: tuple[str, str, str, str],
    t_perdant: tuple[str, str, str, str],
    verdict: str,
    ratio: float,
    motif: str,
) -> dict[str, Any]:
    """MAINTENUE / INVALIDEE (+ tombstone) / révision — WAL tracé, jamais silencieux."""
    for triplet, cible in (
        (t_gagnant, Statut.MAINTENUE if verdict != "revision" else Statut.EN_REVISION),
        (t_perdant, Statut.INVALIDEE if verdict != "revision" else Statut.EN_REVISION),
    ):
        ok, _ = memo.changer_statut(triplet, cible, motif=motif)
        if not ok:
            continue
        if cible is Statut.INVALIDEE:
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
        else:
            env = memo.entites[triplet]
            magasin.append(
                cle,
                Record(
                    stream=cle,
                    op="update_status",
                    key=id_triplet(triplet),
                    data={
                        "triplet": list(triplet),
                        "observation": "",
                        "enveloppe": dict(resume(env)),
                    },
                ),
            )
    return {
        "paire": [list(t_gagnant), list(t_perdant)],
        "verdict": verdict,
        "ratio": ratio,
        "motif": motif,
    }


def cmd_arbitrer(args: argparse.Namespace) -> int:
    """Arbitrage T6.4 (verrou requis ; seuils `[provisoire]` ; T10.4 avant prod)."""
    directive = charger(Path(args.directive))
    prov = directive.seuils_provisoires
    seuils = seuils_sources_directive(directive)
    seuils_tiers = (directive.quality.seuils_tiers[0], directive.quality.seuils_tiers[1])
    maintenant = args.maintenant or datetime.now(UTC).isoformat()
    try:
        magasin = Magasin(Path(args.data_dir))
    except StoreError as exc:
        print(
            json.dumps({"erreur": f"arbitrage impossible : {exc}"}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    try:
        cle = f"domains/{args.domaine}"
        try:
            charge = magasin.recharger(cle)
        except StoreError as exc:
            print(json.dumps({"erreur": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1
        memo, ignores = memoire_depuis_etat(args.domaine, charge.etat, seuils_tiers)
        decisions = []
        for paire in sorted(memo.paires):
            triplets = [t for t in memo.paires[paire] if t in memo.entites]
            if len({t[2] for t in triplets}) < 2:
                continue
            notes = sorted(
                (
                    score_bord(memo, t, magasin, seuils, prov.t_domaine, prov.nmax, maintenant),
                    t,
                )
                for t in triplets
            )
            if len(notes) < 2:
                continue
            (score_b, t_b), (score_a, t_a) = notes[-2], notes[-1]
            verdict, ratio, motif = decider(
                score_a,
                memo.entites[t_a].confirmation_count,
                score_b,
                memo.entites[t_b].confirmation_count,
                seuil=prov.seuil_revision,
            )
            decisions.append(appliquer_verdict(magasin, memo, cle, t_a, t_b, verdict, ratio, motif))
        print(
            json.dumps(
                {"domaine": args.domaine, "decisions": decisions, "ignores_rebuild": ignores},
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        magasin.close()


def consigner_deductions(magasin: Magasin, memo: Memoire, cle: str, deduites: list) -> int:
    """Persiste des arêtes `derived` (T6.6) : `add_edge`, idempotent, tracé."""
    from evidra.memory.envelope import cle_observation, resume

    consignees = 0
    for env in deduites:
        triplet = (memo.domaine, env.cir.source, env.cir.relation, env.cir.target)
        if triplet in memo.entites:
            continue
        observation = cle_observation(env.cir, memo.domaine)
        memo.ajouter(triplet, observation, env)
        magasin.append(
            cle,
            Record(
                stream=cle,
                op="add_edge",
                key=observation,
                data={
                    "triplet": list(triplet),
                    "observation": observation,
                    "enveloppe": dict(resume(env)),
                },
            ),
        )
        consignees += 1
    return consignees


def cmd_deduire(args: argparse.Namespace) -> int:
    """Déduction T6.6 (gate directive, verrou requis, jamais auto)."""
    from evidra.memory.deduction import deduire

    directive = charger(Path(args.directive))
    if directive.deduction != "enabled":
        print(
            json.dumps({"deduites": [], "motif": "déduction interdite par la directive"}),
            file=sys.stderr,
        )
        return 2
    maintenant = args.maintenant or datetime.now(UTC).isoformat()
    try:
        magasin = Magasin(Path(args.data_dir))
    except StoreError as exc:
        print(
            json.dumps({"erreur": f"déduction impossible : {exc}"}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    try:
        cle = f"domains/{args.domaine}"
        try:
            charge = magasin.recharger(cle)
        except StoreError as exc:
            print(json.dumps({"erreur": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1
        memo, ignores = memoire_depuis_etat(args.domaine, charge.etat)
        deduites = deduire(memo.entites, autorise=True, horodatage=maintenant)
        consignees = consigner_deductions(magasin, memo, cle, deduites)
        print(
            json.dumps(
                {
                    "domaine": args.domaine,
                    "proposees": len(deduites),
                    "consignees": consignees,
                    "ignores_rebuild": ignores,
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        magasin.close()


def cmd_lacunes(args: argparse.Namespace) -> int:
    """Lacunes T7.3 : chaînes surveillées → gaps → questions → tâches P4 (verrou)."""
    from datetime import UTC, datetime, timedelta

    from evidra.kernel.contracts import Context
    from evidra.memory.memoire import memoire_depuis_etat
    from evidra.memory.registres import Registres
    from evidra.monitor.lacunes import fiche_tache, planifier
    from evidra.tools.query_gaps import OutilLacunes

    directive = charger(Path(args.directive))
    chaines = [list(c) for c in directive.monitoring.watch_gaps_in_chains if c]
    try:
        magasin = Magasin(Path(args.data_dir))
    except StoreError as exc:
        print(
            json.dumps({"erreur": f"lacunes impossible : {exc}"}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    try:
        cle = f"domains/{args.domaine}"
        try:
            charge = magasin.recharger(cle)
        except StoreError as exc:
            print(json.dumps({"erreur": str(exc)}, ensure_ascii=False), file=sys.stderr)
            return 1
        memo, ignores = memoire_depuis_etat(args.domaine, charge.etat)
        outil = OutilLacunes({args.domaine: memo})
        ctx = Context(store=magasin, domain=args.domaine)
        gaps_par_chaine: dict[str, list[str]] = {}
        injoignables = []
        for chaine in chaines:
            recu = outil.run(ctx, {"chaine": chaine})
            if recu.status is Status.OK:
                gaps_par_chaine[">".join(str(x) for x in chaine)] = [
                    str(g) for g in recu.payload.get("lacunes", []) if isinstance(g, str)
                ]
            else:
                injoignables.append({"chaine": chaine, "motif": recu.payload.get("motif", "")})
        questions = planifier(chaines, gaps_par_chaine)
        registres = Registres(magasin)
        deadline = args.deadline or (datetime.now(UTC) + timedelta(days=7)).isoformat()
        crees = 0
        for rang, question in enumerate(questions):
            if not question.prioritaire:
                continue
            fiche = fiche_tache(question, budget=args.budget, deadline=deadline, rang=rang)
            registres.creer_tache(
                f"lacune-{rang}",
                fiche["type"],
                fiche["budget"],
                fiche["deadline"],
                extras={k: v for k, v in fiche.items() if k not in ("type", "budget", "deadline")},
            )
            crees += 1
        print(
            json.dumps(
                {
                    "domaine": args.domaine,
                    "questions": len(questions),
                    "taches_creees": crees,
                    "injoignables": injoignables,
                    "ignores_rebuild": ignores,
                },
                ensure_ascii=False,
            )
        )
        return 0
    finally:
        magasin.close()
