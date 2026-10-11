# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Enveloppe CIR-noyau / état SA (T2.3, §6.8 + §16.1 de l'étude).

Le CIR-noyau est immuable (fait d'observation) ; l'enveloppe porte l'état
mutable géré par le SA. Deux clés distinctes : clé d'observation (dédup du
rejeu, §6.3 — sans volatiles) et clé de triplet (comptage des confirmations).

Anti-boucle I6 : une arête `derived` exige deux justifications et ne peut
jamais confirmer ses prémisses (le moteur ne l'interdit pas — garde SA).
`normaliser_label` est défini ici une fois pour toutes (T2.5 le réutilise
pour l'index et les alias).
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Statut(StrEnum):
    """Cycle de vie (§6.6) : vocabulaire ici, machine en T6.1."""

    NOUVELLE = "nouvelle"
    ACTIVE = "active"
    CONFIRMEE = "confirmee"
    STALE = "stale"
    EN_REVISION = "en_revision"
    MAINTENUE = "maintenue"
    INVALIDEE = "invalidee"


class Derivation(StrEnum):
    """Origine d'une arête : extraction observée ou déduction tracée."""

    EXTRAITE = "extracted"
    DERIVEE = "derived"


@dataclass(frozen=True, slots=True)
class TokenSpan:
    """Ancrage texte : offsets de l'adaptateur (jamais du moteur)."""

    debut: int
    fin: int


@dataclass(frozen=True, slots=True)
class CodeSpan:
    """Ancrage code : fichier + lignes de l'adaptateur."""

    fichier: str
    ligne_debut: int
    ligne_fin: int


class Synthetic(StrEnum):
    """Relations déduites sans ancrage physique."""

    SYNTHETIC = "synthetic"


Span = TokenSpan | CodeSpan | Synthetic


@dataclass(frozen=True, slots=True)
class Provenance:
    """Provenance statique du CIR-noyau (immuable, §18 + patch P4)."""

    ref: str
    span: Span
    extraction_method: str
    model_version: str
    extracted_at: str
    content_sha256: str = ""
    published_at: str | None = None  # date source, jamais ingestion (§6.9)


@dataclass(frozen=True, slots=True)
class CirCore:
    """CIR-noyau : fait d'observation ponctuel, jamais modifié."""

    source: str
    target: str
    relation: str
    confidence: float
    provenance: Provenance
    explicit: bool = True
    negated: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confiance hors [0,1] : {self.confidence!r}")


@dataclass(slots=True)
class Envelope:
    """Arête enrichie : `cir` immuable + état mutable SA (jamais au moteur)."""

    _cir: CirCore
    status: Statut = Statut.NOUVELLE
    confirmation_count: int = 0
    last_confirmed_at: str | None = None
    source_reliability: float = 0.5  # neutre sous n_min (§16.3)
    ingest_channel: str = ""
    derivation: Derivation = Derivation.EXTRAITE
    quarantine: str | None = None  # motif, None = hors quarantaine
    justifications: tuple[str, ...] = ()

    @property
    def cir(self) -> CirCore:
        """Le CIR-noyau : lecture seule (assigner lève `AttributeError`)."""
        return self._cir


def normaliser_label(label: str) -> str:
    """Casse + accents + espaces, en un seul point (T2.5 réutilise)."""
    sans_accents = "".join(
        c for c in unicodedata.normalize("NFKD", label) if not unicodedata.combining(c)
    )
    return " ".join(sans_accents.casefold().split())


def _span_texte(span: Span) -> str:
    if isinstance(span, TokenSpan):
        return f"t:{span.debut}:{span.fin}"
    if isinstance(span, CodeSpan):
        return f"c:{span.fichier}:{span.ligne_debut}:{span.ligne_fin}"
    return "s"


def cle_observation(cir: CirCore, domaine: str) -> str:
    """Dédup du rejeu : sans `extracted_at`, statut, compteurs (§6.3)."""
    p = cir.provenance
    brut = "|".join(
        [
            domaine,
            normaliser_label(cir.source),
            cir.relation,
            normaliser_label(cir.target),
            p.ref,
            _span_texte(p.span),
            p.extraction_method,
            p.model_version,
        ]
    )
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()


def cle_triplet(cir: CirCore, domaine: str) -> tuple[str, str, str, str]:
    """Comptage des confirmations : (domaine, src, relation, dst) normalisé."""
    return (domaine, normaliser_label(cir.source), cir.relation, normaliser_label(cir.target))


def fabriquer_derivee(cible: CirCore, justif_a: str, justif_b: str) -> Envelope:
    """Déduction tracée : deux justifications distinctes exigées (I6).

    La confiance `min(prémisses)` est calculée par l'appelant (T6.6) et portée
    par `cible` ; ici on scelle la dérivation, jamais les prémisses.
    """
    if not justif_a or not justif_b or justif_a == justif_b:
        raise ValueError("dérivation exige deux justifications distinctes non vides")
    return Envelope(
        cible,
        derivation=Derivation.DERIVEE,
        justifications=(justif_a, justif_b),
    )


def confirmer(cible: Envelope, candidat: Envelope, *, horodatage: str) -> bool:
    """Confirme `cible` par `candidat` s'il est licite ; sinon refuse (I6).

    Une arête `derived` ne confirme jamais (ni ses prémisses ni aucune autre) :
    elle ne change aucun compteur. L'appariement des triplets relève de
    l'ingestion (T3.6) ; ici seule la licéité est tranchée.
    """
    if candidat.derivation is not Derivation.EXTRAITE:
        return False
    cible.confirmation_count += 1
    cible.last_confirmed_at = horodatage
    return True


def resume(enveloppe: Envelope) -> Mapping[str, Any]:
    """Vue JSON de l'enveloppe (WAL, index, API) : noyau + état."""
    cir = enveloppe.cir
    p = cir.provenance
    return {
        "cir": {
            "source": cir.source,
            "target": cir.target,
            "relation": cir.relation,
            "confidence": cir.confidence,
            "explicit": cir.explicit,
            "negated": cir.negated,
            "provenance": {
                "ref": p.ref,
                "span": _span_texte(p.span),
                "extraction_method": p.extraction_method,
                "model_version": p.model_version,
                "extracted_at": p.extracted_at,
            },
        },
        "status": enveloppe.status.value,
        "confirmation_count": enveloppe.confirmation_count,
        "last_confirmed_at": enveloppe.last_confirmed_at,
        "source_reliability": enveloppe.source_reliability,
        "ingest_channel": enveloppe.ingest_channel,
        "derivation": enveloppe.derivation.value,
        "quarantine": enveloppe.quarantine,
        "justifications": list(enveloppe.justifications),
    }
