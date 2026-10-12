# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Registre de sources calculé (T6.3) : compteurs → fiabilité → statut, pur.

`reliability = poids·confirmation_rate + (1−poids)·(1 − contradiction_rate)`
(`[provisoire]`, directive) ; sous `n_min` : 0.5 neutre + `monitored` forcé ;
`trusted` (≥ seuil et contradiction ≤ plafond), `monitored`, `suspect`
(contradiction > seuil ⇒ relations admises en NOUVELLE seulement),
`blocked` (directive/audit, stocké, jamais calculé). Amorçage `monitored`
(§20) : une source inconnue n'est jamais `trusted`. `signaux()` détecte
le basculement vers `suspect` (consommable par le moniteur, phase 7).
L'alimentation `contradicted_*` relève de l'arbitrage (T6.4) : ici
contributions + confirmations indépendantes (ingest), purs calculs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SeuilsSources:
    """Seuils effectifs (extraits de la directive, testables sans disque)."""

    poids_confirmation: float = 0.7
    n_min: int = 5
    seuil_confiance: float = 0.80
    plafond_contradiction: float = 0.05
    seuil_suspect: float = 0.10
    plancher_surveillee: float = 0.60


@dataclass(frozen=True, slots=True)
class Compteurs:
    """Compteurs d'une source (stockés `registry/sources`, jamais à la main)."""

    contribuees: int = 0
    confirmees_indep: int = 0
    contredites_sup: int = 0

    def en_dict(self) -> dict[str, int]:
        return {
            "contribuees": self.contribuees,
            "confirmees_indep": self.confirmees_indep,
            "contredites_sup": self.contredites_sup,
        }

    @staticmethod
    def depuis_dict(brut: Any) -> Compteurs:
        def entier(cle: str) -> int:
            val = brut.get(cle, 0) if isinstance(brut, dict) else 0
            return (
                max(0, int(val))
                if isinstance(val, (int, float)) and not isinstance(val, bool)
                else 0
            )

        return Compteurs(
            contribuees=entier("contribuees"),
            confirmees_indep=entier("confirmees_indep"),
            contredites_sup=entier("contredites_sup"),
        )


def taux_confirmation(c: Compteurs) -> float:
    """`confirmees / contribuees`, 0.0 sous le plancher (jamais levée)."""
    if c.contribuees <= 0:
        return 0.0
    return min(1.0, c.confirmees_indep / c.contribuees)


def taux_contradiction(c: Compteurs) -> float:
    """`contredites / contribuees`, 0.0 sous le plancher (jamais levée)."""
    if c.contribuees <= 0:
        return 0.0
    return min(1.0, c.contredites_sup / c.contribuees)


def fiabilite(c: Compteurs, seuils: SeuilsSources) -> tuple[float, str]:
    """`(score, statut)` : jamais déclaré à la main, amorçage `monitored`."""
    if c.contribuees < seuils.n_min:
        return 0.5, "monitored"
    contra = taux_contradiction(c)
    brut = seuils.poids_confirmation * taux_confirmation(c) + (1.0 - seuils.poids_confirmation) * (
        1.0 - contra
    )
    score = min(1.0, max(0.0, brut))
    if contra > seuils.seuil_suspect:
        return score, "suspect"
    if score >= seuils.seuil_confiance and contra <= seuils.plafond_contradiction:
        return score, "trusted"
    if score >= seuils.plancher_surveillee:
        return score, "monitored"
    return score, "suspect"


def bilan(fiche: Any, seuils: SeuilsSources) -> dict[str, Any]:
    """Fiche stockée → bilan calculé (`blocked` stocké prioritaire)."""
    if isinstance(fiche, dict) and fiche.get("blocked") is True:
        return {
            "fiabilite": 0.0,
            "statut": "blocked",
            "compteurs": Compteurs.depuis_dict(fiche).en_dict(),
        }
    compteurs = Compteurs.depuis_dict(fiche.get("compteurs") if isinstance(fiche, dict) else None)
    score, statut = fiabilite(compteurs, seuils)
    return {"fiabilite": score, "statut": statut, "compteurs": compteurs.en_dict()}


def signale(avant: Compteurs, apres: Compteurs, seuils: SeuilsSources) -> bool:
    """Basculement vers `suspect` : signal consommable par le moniteur (ph. 7)."""
    return fiabilite(avant, seuils)[1] != "suspect" and fiabilite(apres, seuils)[1] == "suspect"
