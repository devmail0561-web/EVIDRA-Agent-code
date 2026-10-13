# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Machine d'états du cycle de vie (T6.1) + décroissance (T6.2) : pur.

`NOUVELLE → ACTIVE` (≥ 2 sources) `→ CONFIRMÉE` (≥ N, N en directive)
`→ STALE` (non re-confirmée depuis T jours) `→ EN RÉVISION`
`→ MAINTENUE | INVALIDÉE` (arbitrage T6.4). Chaque transition réussie mute
`status` et exige un `motif` (tracé WAL `update_status` par l'appelant) ;
illégale ⇒ `(False, motif)` comptable, jamais levée. Pur : ni Store,
ni horloge système (dates injectées).

T6.2 : `fraicheur(t) = exp(-(now − t) / T_domaine)` sur `published_at`
source (jamais date d'ingestion, §6.9) ; inconnu ⇒ 1.0 neutre + flag ;
la confiance *effective* est calculée, le CIR-noyau jamais modifié.
"""

from __future__ import annotations

import math
from datetime import datetime

from evidra.memory.envelope import Derivation, Envelope, Statut

TRANSITIONS: dict[Statut, frozenset[Statut]] = {
    Statut.NOUVELLE: frozenset({Statut.ACTIVE, Statut.INVALIDEE}),
    Statut.ACTIVE: frozenset({Statut.CONFIRMEE, Statut.STALE, Statut.INVALIDEE}),
    Statut.CONFIRMEE: frozenset({Statut.STALE, Statut.EN_REVISION, Statut.INVALIDEE}),
    Statut.STALE: frozenset({Statut.EN_REVISION, Statut.ACTIVE, Statut.INVALIDEE}),
    Statut.EN_REVISION: frozenset({Statut.MAINTENUE, Statut.INVALIDEE, Statut.ACTIVE}),
    Statut.MAINTENUE: frozenset({Statut.STALE, Statut.EN_REVISION, Statut.INVALIDEE}),
    Statut.INVALIDEE: frozenset(),
}


def transition(enveloppe: Envelope, cible: Statut, *, motif: str) -> tuple[bool, str]:
    """`status → cible` si licite ; `(False, rejet)` sinon (comptable)."""
    if not motif or not motif.strip():
        return False, "transition sans motif refusée"
    if cible not in TRANSITIONS[enveloppe.status]:
        return (
            False,
            f"transition illégale : {enveloppe.status.value} → {cible.value}",
        )
    enveloppe.status = cible
    return True, motif


def promouvoir(enveloppe: Envelope, *, n_confirmee: int) -> Statut | None:
    """Promotion par confirmations ; nouveau statut ou `None` (stable).

    `derived` jamais promue ici (I6 : `confirmer` refuse déjà, garde redondante
    explicite). Seuils : ACTIVE dès 2, CONFIRMÉE dès `n_confirmee` (directive).
    """
    if enveloppe.derivation is not Derivation.EXTRAITE:
        return None
    if enveloppe.status is Statut.NOUVELLE and enveloppe.confirmation_count >= 2:
        enveloppe.status = Statut.ACTIVE
        return Statut.ACTIVE
    if enveloppe.status is Statut.ACTIVE and enveloppe.confirmation_count >= n_confirmee:
        enveloppe.status = Statut.CONFIRMEE
        return Statut.CONFIRMEE
    return None


def vieillir(enveloppe: Envelope, *, maintenant_iso: str, stale_after_days: float) -> Statut | None:
    """STALE si non re-confirmée depuis le seuil ; `None` sinon ou illisible.

    `last_confirmed_at` absent ou illisible (naive/aware mélangés inclus) ⇒
    `None`, jamais levée (I12). Ne s'applique qu'aux statuts porteurs de
    confiance (la matrice `transition` tranche le reste).
    """
    if enveloppe.status not in (Statut.ACTIVE, Statut.CONFIRMEE, Statut.MAINTENUE):
        return None
    if not enveloppe.last_confirmed_at:
        return None
    try:
        derniere = datetime.fromisoformat(enveloppe.last_confirmed_at)
        maintenant = datetime.fromisoformat(maintenant_iso)
        depassee = (maintenant - derniere).total_seconds() > stale_after_days * 86400.0  # s/jour
    except (TypeError, ValueError):
        return None
    if not depassee:
        return None
    ok, _ = transition(enveloppe, Statut.STALE, motif="non re-confirmée depuis T jours")
    return Statut.STALE if ok else None


def fraicheur(
    published_at: str | None, *, maintenant_iso: str, t_domaine_jours: float
) -> tuple[float, bool]:
    """`(score, connue)` : `exp(-(now − t) / T)`, `t` = date source (§6.9).

    Inconnue (`None`, vide, illisible) ⇒ `(1.0, False)` neutre + flag ;
    date future ⇒ plafonnée à 1.0. Jamais levée (I12).
    """
    if not published_at or not isinstance(published_at, str):
        return 1.0, False
    try:
        publie = datetime.fromisoformat(published_at)
        maintenant = datetime.fromisoformat(maintenant_iso)
        age_jours = (maintenant - publie).total_seconds() / 86400.0
    except (TypeError, ValueError):
        return 1.0, False
    if age_jours <= 0.0:
        return 1.0, True
    if t_domaine_jours <= 0.0:
        return 1.0, True
    return math.exp(-age_jours / t_domaine_jours), True


def confiance_effective(
    enveloppe: Envelope, *, maintenant_iso: str, t_domaine_jours: float
) -> tuple[float, bool]:
    """Confiance CIR × fraîcheur (`(score, fraicheur_connue)`, CIR intact)."""
    score, connue = fraicheur(
        enveloppe.cir.provenance.published_at,
        maintenant_iso=maintenant_iso,
        t_domaine_jours=t_domaine_jours,
    )
    return enveloppe.cir.confidence * score, connue


def recenser_stales(
    entites: dict[tuple[str, str, str, str], Envelope],
    *,
    maintenant_iso: str,
    stale_after_days: float,
    t_domaine_jours: float,
) -> list[dict[str, object]]:
    """Candidats maintenance P5 : entités relevant de `vieillir`, triées.

    Pur (lecture seule) : chaque fiche porte triplet, statut, confiance
    effective, fraîcheur et sa connaissance. La création de tâches P5
    relève du consommateur `maintenance` (T6.4).
    """
    fiches = []
    for triplet, enveloppe in sorted(entites.items()):
        if enveloppe.status not in (Statut.ACTIVE, Statut.CONFIRMEE, Statut.MAINTENUE):
            continue
        if enveloppe.last_confirmed_at is None:
            continue
        try:
            derniere = datetime.fromisoformat(enveloppe.last_confirmed_at)
            maintenant = datetime.fromisoformat(maintenant_iso)
            age = (maintenant - derniere).total_seconds() / 86400.0
        except (TypeError, ValueError):
            continue
        if age <= stale_after_days:
            continue
        effective, connue = confiance_effective(
            enveloppe, maintenant_iso=maintenant_iso, t_domaine_jours=t_domaine_jours
        )
        fiches.append(
            {
                "triplet": list(triplet),
                "statut": enveloppe.status.value,
                "confiance_effective": effective,
                "fraicheur_connue": connue,
                "age_jours": age,
            }
        )
    return fiches
