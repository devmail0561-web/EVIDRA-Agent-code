# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Sorties réseau contrôlées (T9.9) : verbe `egress` + liste blanche d'hôtes.

Tout appel sortant passe par le verbe `egress` (porte `can()`) et une liste
blanche d'hôtes déclarée dans la directive (`Sortie.egress_hotes`). Pur,
testé, fail-closed : hôte absent de la liste ⇒ refus motivé, jamais d'envoi.
"""

from __future__ import annotations

from urllib.parse import urlparse


def hote_de(url: str) -> str | None:
    """Hôte d'une URL, `None` si illisible."""
    try:
        hote = urlparse(url).hostname
    except ValueError:
        return None
    return hote.lower() if hote else None


def hote_autorise(url: str, hotes: list[str] | tuple[str, ...] | set[str] | None) -> bool:
    """Vrai si l'hôte de `url` figure dans la liste blanche (insensible à la casse).

    `hotes=None` ⇒ pas de liste configurée : héritage ouvert (appelant sans
    directive ; la directive câblée en T9.9 passe toujours sa liste).
    """
    if hotes is None:
        return True
    hote = hote_de(url)
    if hote is None:
        return False
    autorises = {h.lower() for h in hotes if isinstance(h, str)}
    return hote in autorises


def verifier_egress(
    url: str, hotes: list[str] | tuple[str, ...] | set[str] | None
) -> tuple[bool, str]:
    """`(ok, motif)` : fail-closed avant tout envoi."""
    if not isinstance(url, str) or not url.strip():
        return False, "egress refusé : URL vide"
    if hote_autorise(url, hotes):
        return True, "ok"
    return False, f"egress refusé : hôte hors liste blanche ({hote_de(url) or 'illisible'})"
