#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Runner du benchmark agentique MVP (T10.1) : ingest → validate → chaînes → flux.

Sans moteur (engine-free, déterministe) : triplets structurés (pas de NLP),
détecteurs T9.4 pour le flux. Mesure, ne prétend pas : 200 claims (100
CONFIRMED / 60 UNCONFIRMED / 40 CONTRADICTED), 50 chaînes à chemin connu,
1012 documents dont 12 anomalies (quarantaine attendue).
Sortie : objet JSON daté sur stdout, écrit dans `--sortie` si fourni.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
CORPUS_DEFAUT = RACINE / "benchmarks" / "agentique-mvp.json"

sys.path.insert(0, str(RACINE / "src"))

from evidra.kernel.contracts import Context  # noqa: E402
from evidra.memory.envelope import CirCore, Provenance, normaliser_label  # noqa: E402
from evidra.memory.memoire import Memoire  # noqa: E402
from evidra.memory.store import Magasin  # noqa: E402
from evidra.security.content import analyser as analyser_contenu  # noqa: E402
from evidra.tools.validate import OutilValider  # noqa: E402

CONFIANCE_MVP = 0.9  # confiance simulée d'extraction (protocole, pas une mesure)
DOMAINE = "mvp"


def charger_corpus(chemin: Path) -> dict:
    """Corpus figé ; clés manquantes ⇒ `KeyError` (échec explicite, pas de défaut)."""
    corpus = json.loads(chemin.read_text(encoding="utf-8"))
    for cle in ("graine", "documents", "claims", "chaines"):
        if cle not in corpus:
            raise KeyError(f"corpus incomplet : {cle!r} absent")
    return corpus


def _noyau(triplet: list, ref: str, published_at: str) -> CirCore:
    return CirCore(
        source=str(triplet[0]),
        target=str(triplet[2]),
        relation=str(triplet[1]),
        confidence=CONFIANCE_MVP,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="benchmark-mvp",
            extracted_at=published_at,
            published_at=published_at,
        ),
    )


def construire_memoire(corpus: dict) -> tuple[Memoire, dict[str, int]]:
    """Ingest vérité + quarantaine des anomalies (détecteurs, pas de moteur)."""
    memo = Memoire(DOMAINE)
    stats = {"ajoutees": 0, "confirmees": 0, "idempotentes": 0, "quarantaines": 0}
    for doc in corpus["documents"]:
        motifs = analyser_contenu(str(doc["texte"]), str(doc["ref"]))
        quarantaine = motifs[0] if motifs else None
        for triplet in doc["triplets"]:
            issue = memo.observer(
                _noyau(triplet, str(doc["ref"]), str(doc["published_at"])),
                channel="local_files",
                fiabilite=0.5,
                horodatage=str(doc["published_at"]),
                quarantaine=quarantaine,
            )
            if issue.sorte == "nouvelle":
                stats["ajoutees"] += 1
            elif issue.sorte == "confirmation":
                stats["confirmees"] += 1
            else:
                stats["idempotentes"] += 1
        if quarantaine is not None:
            stats["quarantaines"] += 1
    return memo, stats


def scorer_claims(memo: Memoire, claims: list, magasin: Magasin) -> dict[str, float | int]:
    """Exactitude par verdict (triplets structurés, déterministe)."""
    outil = OutilValider({DOMAINE: memo})
    ctx = Context(store=magasin, domain=DOMAINE)
    bons = {"CONFIRMED": 0, "UNCONFIRMED": 0, "CONTRADICTED": 0}
    totaux = {"CONFIRMED": 0, "UNCONFIRMED": 0, "CONTRADICTED": 0}
    for claim in claims:
        t = claim["triplet"]
        recu = outil.run(ctx, {"claim": {"source": t[0], "relation": t[1], "cible": t[2]}})
        verdict = recu.payload.get("verdict")
        totaux[claim["verdict"]] += 1
        if verdict == claim["verdict"]:
            bons[claim["verdict"]] += 1
    return {
        "exactitude_confirmed": bons["CONFIRMED"] / totaux["CONFIRMED"],
        "exactitude_unconfirmed": bons["UNCONFIRMED"] / totaux["UNCONFIRMED"],
        "exactitude_contradicted": bons["CONTRADICTED"] / totaux["CONTRADICTED"],
        "exactitude_globale": sum(bons.values()) / sum(totaux.values()),
        "bons": sum(bons.values()),
        "total": sum(totaux.values()),
    }


def scorer_chaines(memo: Memoire, chaines: list) -> dict[str, int]:
    """Chaînes dont chaque maillon est présent et hors quarantaine."""
    trouvees = 0
    for chaine in chaines:
        noeuds = [normaliser_label(str(n)) for n in chaine]
        ok = True
        for a, b in zip(noeuds, noeuds[1:], strict=False):
            candidats = memo.paires.get((DOMAINE, a, b), [])
            if not any(
                memo.entites.get(t) is not None and memo.entites[t].quarantine is None
                for t in candidats
            ):
                ok = False
                break
        trouvees += int(ok)
    return {"trouvees": trouvees, "total": len(chaines)}


def scorer_flux(corpus: dict) -> dict[str, int]:
    """Anomalies détectées (rappel) + documents honnêtes épargnés (FP)."""
    attendues = rappel = honnetes = fp = 0
    for doc in corpus["documents"]:
        motifs = analyser_contenu(str(doc["texte"]), str(doc["ref"]))
        annonce = doc.get("anomalie")
        attendus = annonce.get("motifs", []) if isinstance(annonce, dict) else []
        if attendus:
            attendues += 1
            rappel += int(bool(motifs) and motifs[0] == attendus[0])
        else:
            honnetes += 1
            fp += int(bool(motifs))
    return {
        "anomalies": attendues,
        "anomalies_detectees": rappel,
        "rappel_quarantaine": rappel / attendues if attendues else 1.0,
        "honnetes": honnetes,
        "faux_positifs": fp,
    }


def mesurer(corpus_chemin: Path = CORPUS_DEFAUT) -> dict:
    """Construit, score, chronomètre ; jamais de réseau ni de moteur."""
    corpus = charger_corpus(corpus_chemin)
    debut = time.monotonic()
    with Magasin(Path(tempfile.mkdtemp()) / "bench") as magasin:
        memo, ingest = construire_memoire(corpus)
        claims = scorer_claims(memo, corpus["claims"], magasin)
        chaines = scorer_chaines(memo, corpus["chaines"])
    duree = time.monotonic() - debut
    flux = scorer_flux(corpus)
    return {
        "date": datetime.now(UTC).isoformat(),
        "graine": corpus["graine"],
        "documents": len(corpus["documents"]),
        "entites": len(memo.entites),
        "ingest": ingest,
        "claims": claims,
        "chaines": chaines,
        "flux": flux,
        "duree_s": round(duree, 3),
        "docs_s": round(len(corpus["documents"]) / duree, 1) if duree > 0 else 0.0,
    }


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--corpus", default=str(CORPUS_DEFAUT))
    args.add_argument("--sortie", default="")
    opts = args.parse_args()
    rapport = mesurer(Path(opts.corpus))
    texte = json.dumps(rapport, indent=2, ensure_ascii=False)
    print(texte)
    if opts.sortie:
        Path(opts.sortie).write_text(texte + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
