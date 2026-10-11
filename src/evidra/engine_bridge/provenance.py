# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Enveloppement de provenance (T3.2, §18 + patch P4) : `ref`+`span` réels.

Le moteur Python émet `ref=None` et un span marqueur ; le SA injecte `ref`
(document connu de l'adaptateur), le span réel (`TokenSpan`/`CodeSpan` fourni
par l'adaptateur, `Synthetic` sinon) et `content_sha256` **par-dessus**, sans
toucher aux autres champs du CIR-noyau. Aucune modification du moteur.
La table de l'adaptateur est autoritaire : un span fourni écrase le marqueur.

`verifier` = re-hash + comparaison (échec ⇒ `ref_invérifiable` → quarantaine,
§28.3, tranché en T3.6). `vers_noyaux` convertit le CIR enrichi en `CirCore`
sans perte (`explicit`/`negated` conservés).
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping
from typing import Any

from evidra.memory.envelope import (
    CirCore,
    CodeSpan,
    Provenance,
    Span,
    Synthetic,
    TokenSpan,
    span_depuis_dict,
    span_vers_dict,
)


def envelopper(
    cir: Mapping[str, Any], *, ref: str, texte: str, spans: Mapping[Any, Span] | None = None
) -> dict[str, Any]:
    """Injecte provenance réelle dans une copie (jamais de mutation partagée)."""
    if not isinstance(cir, Mapping):
        raise ValueError("CIR : dictionnaire exigé")
    if not isinstance(ref, str) or not ref:
        raise ValueError("ref : document connu de l'adaptateur exigé")
    if not isinstance(texte, str):
        raise ValueError("texte source exigé (hash de revérification)")
    noeuds, aretes = cir.get("nodes"), cir.get("edges")
    if not isinstance(noeuds, list) or not isinstance(aretes, list):
        raise ValueError("CIR mal formé : `nodes`/`edges` listes exigées")
    copie = copy.deepcopy(dict(cir))
    empreinte = hashlib.sha256(texte.encode("utf-8")).hexdigest()
    for arete in copie["edges"]:
        attrs = arete[2] if isinstance(arete, (list, tuple)) and len(arete) == 3 else None
        if not isinstance(attrs, dict):
            raise ValueError("CIR mal formé : arête [src, dst, attrs] exigée")
        prov = attrs.get("provenance")
        if not isinstance(prov, dict):
            raise ValueError("CIR mal formé : provenance absente (jamais inventée)")
        if prov.get("ref") is None:
            prov["ref"] = ref
        if spans is not None and attrs.get("marker_token") in spans:
            prov["span"] = serialiser_span(cast_span(spans[attrs["marker_token"]]))
        prov["content_sha256"] = empreinte
    return copie


def cast_span(span: Span) -> Span:
    """Garde de type : seul `TokenSpan | CodeSpan | Synthetic` passe."""
    if isinstance(span, (TokenSpan, CodeSpan, Synthetic)):
        return span
    raise ValueError(f"span inconnu : {span!r}")


def serialiser_span(span: Span) -> Any:
    """Délègue à `span_vers_dict` (référence unique côté mémoire)."""
    return span_vers_dict(span)


def _parse_span(brut: Any) -> Span:
    """Délègue à `span_depuis_dict` (référence unique côté mémoire)."""
    return span_depuis_dict(brut)


def verifier(cir_enrichi: Mapping[str, Any], texte: str) -> bool:
    """Re-hash + comparaison : `True` si chaque arête cite ce texte (I4)."""
    if not isinstance(cir_enrichi, Mapping) or not isinstance(texte, str):
        return False
    aretes = cir_enrichi.get("edges")
    if not isinstance(aretes, list):
        return False
    empreinte = hashlib.sha256(texte.encode("utf-8")).hexdigest()
    for arete in aretes:
        attrs = arete[2] if isinstance(arete, (list, tuple)) and len(arete) == 3 else None
        prov = attrs.get("provenance") if isinstance(attrs, dict) else None
        if not isinstance(prov, dict):
            return False
        if not prov.get("ref") or prov.get("content_sha256") != empreinte:
            return False
    return True


def vers_noyaux(cir_enrichi: Mapping[str, Any]) -> list[CirCore]:
    """CIR enrichi → un `CirCore` par arête, sans perte (ref exigée)."""
    if not isinstance(cir_enrichi, Mapping):
        raise ValueError("CIR : dictionnaire exigé")
    noeuds, aretes = cir_enrichi.get("nodes"), cir_enrichi.get("edges")
    if not isinstance(noeuds, list) or not isinstance(aretes, list):
        raise ValueError("CIR mal formé : `nodes`/`edges` listes exigées")
    labels: dict[Any, str] = {}
    for noeud in noeuds:
        if isinstance(noeud, Mapping) and "id" in noeud:
            labels[noeud["id"]] = str(noeud.get("label", f"node:{noeud['id']}"))
    noyaux: list[CirCore] = []
    for arete in aretes:
        if not (
            isinstance(arete, (list, tuple)) and len(arete) == 3 and isinstance(arete[2], dict)
        ):
            raise ValueError("CIR mal formé : arête [src, dst, attrs] exigée")
        src, dst, attrs = arete
        relation = attrs.get("relation")
        if not isinstance(relation, str) or not relation:
            raise ValueError("arête sans relation")
        prov = attrs.get("provenance")
        if not isinstance(prov, dict) or not prov.get("ref"):
            raise ValueError("provenance sans ref — envelopper d'abord (I4)")
        noyaux.append(
            CirCore(
                source=labels.get(src, f"node:{src}"),
                target=labels.get(dst, f"node:{dst}"),
                relation=relation,
                confidence=float(attrs.get("confidence", 0.0)),
                provenance=Provenance(
                    ref=str(prov["ref"]),
                    span=_parse_span(prov.get("span")),
                    extraction_method=str(prov.get("extraction_method", "")),
                    model_version=str(prov.get("model_version", "")),
                    extracted_at=str(prov.get("extracted_at", "")),
                    content_sha256=str(prov.get("content_sha256", "")),
                ),
                explicit=bool(attrs.get("explicit", True)),
                negated=bool(attrs.get("negated", False)),
            )
        )
    return noyaux
