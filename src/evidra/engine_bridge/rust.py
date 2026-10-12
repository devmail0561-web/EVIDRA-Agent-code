# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Requêtes GCN-QL via le CLI Rust (T5.2/T5.4, ADR-0012) : Dijkstra sans réécrire.

`gcn query --ir F.requete` (subprocess isolé, timeout, JSON validé,
fail-closed) : le moteur Rust calcule les chemins confiance-max (Dijkstra
+ Yen, constaté `pearl.rs`). AUCUNE réimplémentation côté SA (ADR-10).
`--essai` n'a pas de sens ici : sans binaire, DEGRADE explicite (jamais de
repli BFS silencieux qui changerait la sémantique).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from evidra.memory.envelope import span_vers_dict


class RustIndisponible(Exception):  # noqa: N818 — vocabulaire SA (cf. T1.6)
    """CLI Rust absent, en timeout ou sortie illisible (fail-closed)."""


def interroger_chaine(
    binaire: str, iri: dict[str, Any], de_label: str, vers_label: str, *, timeout_s: float = 30.0
) -> dict[str, Any]:
    """`CHAIN a -> b?` sur un IR dict : réponse JSON validée (top-k moteur)."""
    for label in (de_label, vers_label):
        if not isinstance(label, str) or not label.strip() or "\n" in label:
            raise ValueError(f"label de requête invalide : {label!r}")
    if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
        raise ValueError(f"timeout invalide : {timeout_s!r}")
    requete = f"CHAIN {de_label.strip()} -> {vers_label.strip()}?"
    ir_path = Path("chaine_ir.json")
    try:
        ir_path.write_text(json.dumps(iri), encoding="utf-8")
        acheve = subprocess.run(
            [binaire, "query", "--ir", str(ir_path), requete],
            capture_output=True,
            text=True,
            timeout=float(timeout_s),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RustIndisponible(f"sous-processus gcn : {exc}") from None
    finally:
        ir_path.unlink(missing_ok=True)
    try:
        reponse = json.loads(acheve.stdout)
    except ValueError:
        raise RustIndisponible(
            f"sortie gcn illisible : {acheve.stdout[:200]!r} / {acheve.stderr[:200]!r}"
        ) from None
    if not isinstance(reponse, dict):
        raise RustIndisponible(f"réponse inattendue : {str(reponse)[:200]!r}")
    # Binaire récent : enveloppe always-answer ; ancien : résultat nu (toléré).
    resultat = reponse.get("result")
    if not isinstance(resultat, dict):
        resultat = reponse
    if "found" not in resultat:
        raise RustIndisponible(f"réponse inattendue : {str(resultat)[:200]!r}")
    return resultat


# Méthodes comprises par le CLI Rust (enum fermée côté moteur).
METHODES_RUST = frozenset({"symbolic_rust", "ml_python", "silver_annotator", "derived"})


def serialiser_iri(
    enveloppes: list[tuple[str, str, str, float, bool, dict[str, Any]]],
) -> dict[str, Any]:
    """Enveloppes → IR dict forme Python-émetteur (validé par le CLI Rust).

    Entrée par arête : `(src_label, dst_label, relation, confiance, negated,
    provenance_dict)`. Ids entiers (u32), `node_type` générique `concept`,
    `origin` explicite (observations extraites — sinon Dijkstra les pénalise
    à 0.7, constaté `pearl.rs`), spans token ou `"synthetic"` (fin au mot =
    T5.4). Approximations documentées, jamais persistées (requête seule).
    """
    labels: dict[str, int] = {}
    nodes = []
    for src, dst, _rel, _conf, _neg, _prov in enveloppes:
        for label in (src, dst):
            if label not in labels:
                labels[label] = len(labels)
                nodes.append(
                    {
                        "id": labels[label],
                        "node_type": "concept",
                        "label": label,
                        "source_span": {"token_span": {"start": 0, "end": 0}},
                        "scope": "unknown",
                        "modifiers": [],
                        "temporal_ref": "unresolved",
                        "temporal_index": 0,
                        "origin": "explicit",
                        "is_inferred": False,
                        "attributes": {},
                    }
                )
    edges = []
    for src, dst, relation, confiance, negated, prov in enveloppes:
        methode = prov.get("extraction_method", "")
        if methode not in METHODES_RUST:
            raise ValueError(f"méthode d'extraction inconnue du CLI Rust : {methode!r}")
        span = prov.get("span", "synthetic")
        if isinstance(span, dict) and isinstance(span.get("token_span"), dict):
            token = span["token_span"]
            if isinstance(token.get("start"), int) and isinstance(token.get("end"), int):
                span_out: Any = {"token_span": {"start": token["start"], "end": token["end"]}}
            else:
                span_out = "synthetic"
        else:
            try:
                span_out = span_vers_dict(span)
            except ValueError:
                span_out = "synthetic"
        edges.append(
            [
                labels[src],
                labels[dst],
                {
                    "relation": relation,
                    "confidence": float(confiance),
                    "explicit": True,
                    "negated": bool(negated),
                    "provenance": {
                        "ref": prov.get("ref"),
                        "span": span_out,
                        "extraction_method": prov.get("extraction_method", ""),
                        "model_version": prov.get("model_version", ""),
                        "extracted_at": prov.get("extracted_at", ""),
                    },
                },
            ]
        )
    return {
        "source_text": "",
        "source_lang": {"natural": {"lang": "und"}},
        "nodes": nodes,
        "edges": edges,
        "cycles": [],
        "unresolved": [],
        "metadata": {"schema_version": "2.0", "pipeline": ["evidra-requete"], "created_at": ""},
    }
