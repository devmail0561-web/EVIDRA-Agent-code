#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Générateur du benchmark agentique MVP (T10.1) : 1000 docs, 200 claims, 50 chaînes.

Déterministe (`--graine`, défaut 42) : même graine ⇒ même corpus octet pour
octet (tri JSON, pas de `set` itéré). Vérité causale synthétique CTI, relations
`cause`/`prevent` (table d'opposition fermée de l'outil `validate`).
Sortie : `benchmarks/agentique-mvp.json` (référence figée, relue par le runner
et les tests — on ne régénère qu'en changeant la graine, avec ADR).
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SORTIE_DEFAUT = RACINE / "benchmarks" / "agentique-mvp.json"

sys.path.insert(0, str(RACINE / "src"))

from evidra.security.content import INJONCTIONS as INJONCTIONS_CANONIQUES  # noqa: E402

SOURCES = [
    "hameconnage-cible",
    "rancongiciel-lockbit",
    "exploit-cve-2024-1101",
    "macro-piegee",
    "cle-usb-perdue",
    "mandataire-compromis",
    "serveur-non-patche",
    "vpn-sans-mfa",
    "sauvegarde-absente",
    "segmentation-manquante",
    "journalisation-coupee",
    "compte-service-surprivilegie",
    "faux-support-telephonique",
    "document-office-arme",
    "pilote-vulnerable",
    "api-publique-exposee",
    "mot-de-passe-reutilise",
    "session-rdp-ouverte",
    "fournisseur-pirate",
    "mise-a-jour-retardee",
]
CIBLES = [
    "chiffrement-postes",
    "exfiltration-donnees",
    "paralysie-caisses",
    "vol-identifiants",
    "propagation-reseau",
    "destruction-sauvegardes",
    "fraude-virement",
    "espionnage-plans",
    "saturation-serveurs",
    "alteration-journaux",
    "prise-controle-ad",
    "rancon-exigee",
    "fuite-clients",
    "arret-usine",
    "desactivation-antivirus",
    "persistance-registre",
    "rebond-filiales",
    "chantage-publication",
    "corruption-bases",
    "interception-courriels",
]
NOEUDS_CHAINE = [f"maillon-{i:02d}" for i in range(150)]
RELATIONS = ["cause", "prevent", "enable", "block"]
OPPOSES = {"cause": "prevent", "prevent": "cause", "enable": "block", "block": "enable"}

INJONCTIONS = [i for i in INJONCTIONS_CANONIQUES if "oublie" in i or "ignore" in i][:6]
"""Sous-ensemble FR de la liste canonique (`security.content`, source unique)."""
FAUSSES_REFS = ["ftp://evil.example.org/preuve", "file:///definitivement/absent/preuve.txt"]


def _triplets_verite(hasard: random.Random) -> tuple[list[list[str]], list[list[str]]]:
    """`(triplets, chaines)` : 50 chaînes A→B→C + 1300 arêtes aléatoires, dédupées."""
    triplets: list[list[str]] = []
    chaines: list[list[str]] = []
    vus: set[tuple[str, str, str]] = set()
    for i in range(50):
        a, b, c = NOEUDS_CHAINE[3 * i], NOEUDS_CHAINE[3 * i + 1], NOEUDS_CHAINE[3 * i + 2]
        for t in ([a, "cause", b], [b, "cause", c]):
            if tuple(t) not in vus:
                vus.add(tuple(t))
                triplets.append(t)
        chaines.append([a, b, c])
    while len(triplets) < 1400:
        t = [hasard.choice(SOURCES), hasard.choice(RELATIONS), hasard.choice(CIBLES)]
        if tuple(t) not in vus:
            vus.add(tuple(t))
            triplets.append(t)
    triplets.sort()
    chaines.sort()
    return triplets, chaines


def _documents(hasard: random.Random, triplets: list[list[str]]) -> list[dict[str, object]]:
    """1000 documents (1–2 triplets), 24 h + 12 anomalies ; chaque triplet porté ≥ 1 fois."""
    melanges = list(triplets)
    hasard.shuffle(melanges)
    docs = []
    slot = 0
    for i in range(1000):
        contenus = [melanges[slot % len(melanges)]]
        slot += 1
        if i % 2 == 0:
            contenus.append(melanges[slot % len(melanges)])
            slot += 1
        phrases = [f"{t[0]} {t[1]} {t[2]}." for t in contenus]
        heure = (i * 24) // 1000
        docs.append(
            {
                "id": f"mvp-{i:04d}",
                "texte": " ".join(phrases),
                "ref": f"doc://mvp/{i:04d}",
                "published_at": f"2026-01-01T{heure:02d}:00:00+00:00",
                "triplets": contenus,
                "anomalie": None,
            }
        )
    assert slot >= len(melanges), "couverture vérité incomplète"
    for k in range(12):
        if k < 6:
            docs.append(
                {
                    "id": f"mvp-adv-i{k}",
                    "texte": f"{INJONCTIONS[k % len(INJONCTIONS)]} : "
                    f"{SOURCES[k]} cause {CIBLES[k]}.",
                    "ref": f"doc://mvp/adv-i{k}",
                    "published_at": f"2026-01-01T{(12 + k):02d}:00:00+00:00",
                    "triplets": [],
                    "anomalie": {"motifs": ["instruction"]},
                }
            )
        else:
            j = k - 6
            docs.append(
                {
                    "id": f"mvp-adv-p{j}",
                    "texte": f"{SOURCES[j]} cause {CIBLES[j]}.",
                    "ref": FAUSSES_REFS[j % len(FAUSSES_REFS)],
                    "published_at": f"2026-01-01T{(18 + j):02d}:00:00+00:00",
                    "triplets": [],
                    "anomalie": {"motifs": ["provenance_forgee"]},
                }
            )
    docs.sort(key=lambda d: (str(d["published_at"]), str(d["id"])))
    return docs


def _claims(hasard: random.Random, triplets: list[list[str]]) -> list[dict[str, object]]:
    """200 claims : 100 CONFIRMED (vérité) + 60 UNCONFIRMED + 40 CONTRADICTED."""
    verite = {tuple(t) for t in triplets}
    paires = {(t[0], t[2]) for t in triplets}
    claims: list[dict[str, object]] = []
    for t in hasard.sample(triplets, 100):
        claims.append({"triplet": t, "verdict": "CONFIRMED"})
    ajoutes = 0
    while ajoutes < 60:
        # Espace disjoint de la vérité (cible maillon) : terminaison garantie.
        t = [hasard.choice(SOURCES), hasard.choice(RELATIONS), hasard.choice(NOEUDS_CHAINE)]
        if tuple(t) not in verite and (t[0], t[2]) not in paires:
            claims.append({"triplet": t, "verdict": "UNCONFIRMED"})
            paires.add((t[0], t[2]))
            ajoutes += 1
    ajoutes = 0
    melanges = hasard.sample(triplets, len(triplets))
    for t in melanges:
        if ajoutes >= 40:
            break
        oppose = [t[0], OPPOSES[t[1]], t[2]]
        if tuple(oppose) not in verite:
            claims.append({"triplet": oppose, "verdict": "CONTRADICTED"})
            verite.add(tuple(oppose))
            ajoutes += 1
    assert ajoutes == 40, f"contradictoires : {ajoutes}"
    claims.sort(key=lambda c: (str(c["verdict"]), str(c["triplet"])))
    assert len(claims) == 200, f"claims : {len(claims)}"
    return claims


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--graine", type=int, default=42)
    args.add_argument("--sortie", default=str(SORTIE_DEFAUT))
    opts = args.parse_args()
    hasard = random.Random(opts.graine)
    triplets, chaines = _triplets_verite(hasard)
    corpus = {
        "graine": opts.graine,
        "documents": _documents(hasard, triplets),
        "claims": _claims(hasard, triplets),
        "chaines": chaines,
    }
    sortie = Path(opts.sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text(json.dumps(corpus, indent=1, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps({k: len(v) for k, v in corpus.items() if isinstance(v, list)}))


if __name__ == "__main__":
    sys.exit(main())
