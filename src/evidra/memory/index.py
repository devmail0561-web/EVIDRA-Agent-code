# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Index inversé (T2.5) : O(n)→O(k) sur les requêtes par label.

`label` (exact normalisé, repli tokens), `relation`, tiers de confiance
(seuils `[provisoire]` depuis la directive `quality.seuils_tiers`, I9 —
source unique `directive.schema`, jamais de constante ici). Construction
unique après chargement (`reconstruire`), mise à jour O(1) à l'insertion,
retrait propre sur tombstone (`retirer`). Normalisation via
`normaliser_label` (fonction unique, T2.3 — alias T6.5 réutilise).
"""

from __future__ import annotations

from dataclasses import dataclass

from evidra.directive.schema import seuils_tiers_defaut
from evidra.memory.envelope import normaliser_label


def tier(confiance: float, haut: float, moyen: float) -> str:
    """Tier d'une confiance selon des seuils explicites (jamais de défaut dur)."""
    if confiance >= haut:
        return "high"
    if confiance >= moyen:
        return "medium"
    return "low"


@dataclass(slots=True)
class _Arete:
    src: str
    dst: str
    tokens: frozenset[str]
    relation: str
    tier: str


class Index:
    """Index d'un domaine : arêtes adressables par label, tokens, relation."""

    def __init__(self, seuils: tuple[float, float] | None = None) -> None:
        haut, moyen = seuils if seuils is not None else seuils_tiers_defaut()
        if not 0.0 <= moyen <= haut <= 1.0:
            raise ValueError(f"seuils de tiers invalides : {(haut, moyen)}")
        self._seuil_haut = haut
        self._seuil_moyen = moyen
        self._aretes: dict[str, _Arete] = {}
        self._depuis: dict[str, set[str]] = {}
        self._vers: dict[str, set[str]] = {}
        self._tokens: dict[str, set[str]] = {}
        self._relations: dict[str, set[str]] = {}
        self._tiers: dict[str, set[str]] = {}

    def __len__(self) -> int:
        return len(self._aretes)

    def ajouter(self, ident: str, src: str, dst: str, relation: str, confiance: float) -> None:
        """Insertion O(1) (remplace l'entrée existante sous le même id)."""
        if ident in self._aretes:
            self.retirer(ident)
        src_n, dst_n = normaliser_label(src), normaliser_label(dst)
        tokens = frozenset(src_n.split()) | frozenset(dst_n.split())
        arete = _Arete(
            src=src_n,
            dst=dst_n,
            tokens=tokens,
            relation=relation,
            tier=tier(confiance, self._seuil_haut, self._seuil_moyen),
        )
        self._aretes[ident] = arete
        self._depuis.setdefault(src_n, set()).add(ident)
        self._vers.setdefault(dst_n, set()).add(ident)
        for token in tokens:
            self._tokens.setdefault(token, set()).add(ident)
        self._relations.setdefault(relation, set()).add(ident)
        self._tiers.setdefault(arete.tier, set()).add(ident)

    def retirer(self, ident: str) -> None:
        """Retrait propre (tombstone) : aucune entrée orpheline."""
        arete = self._aretes.pop(ident, None)
        if arete is None:
            return
        for table, cles in (
            (self._depuis, (arete.src,)),
            (self._vers, (arete.dst,)),
            (self._tokens, tuple(arete.tokens)),
            (self._relations, (arete.relation,)),
            (self._tiers, (arete.tier,)),
        ):
            for cle in cles:
                ids = table.get(cle)
                if ids is not None:
                    ids.discard(ident)
                    if not ids:
                        del table[cle]

    def reconstruire(self, entrees: dict[str, tuple[str, str, str, float]]) -> None:
        """Construction unique après chargement : vide puis insère tout."""
        self._aretes.clear()
        self._depuis.clear()
        self._vers.clear()
        self._tokens.clear()
        self._relations.clear()
        self._tiers.clear()
        for ident, (src, dst, relation, confiance) in entrees.items():
            self.ajouter(ident, src, dst, relation, confiance)

    def causes(self, label: str) -> tuple[str, ...]:
        """Ids des arêtes causant `label` (exact normalisé, repli tokens)."""
        cible = normaliser_label(label)
        trouves = self._vers.get(cible)
        if trouves:
            return tuple(sorted(trouves))
        unions: set[str] = set()
        for token in cible.split():
            unions |= self._tokens.get(token, set())
        return tuple(sorted(unions))

    def effets(self, label: str) -> tuple[str, ...]:
        """Ids des arêtes dont `label` est la cause (miroir de `causes`)."""
        cible = normaliser_label(label)
        trouves = self._depuis.get(cible)
        if trouves:
            return tuple(sorted(trouves))
        unions: set[str] = set()
        for token in cible.split():
            unions |= self._tokens.get(token, set())
        return tuple(sorted(unions))

    def par_sous_chaine(self, fragment: str, limite: int = 50) -> tuple[str, ...]:
        """Dernier recours borné : ids dont un token contient le fragment."""
        frag = normaliser_label(fragment)
        if not frag:
            return ()
        ids: set[str] = set()
        for token, porteurs in self._tokens.items():
            if frag in token:
                ids |= porteurs
                if len(ids) >= limite:
                    break
        return tuple(sorted(ids)[:limite])

    def par_relation(self, relation: str) -> tuple[str, ...]:
        """Ids des arêtes d'une relation."""
        return tuple(sorted(self._relations.get(relation, ())))

    def sortants(self, label: str) -> tuple[str, ...]:
        """Ids partant de `label` (exact normalisé, sans repli — BFS T3.4)."""
        return tuple(sorted(self._depuis.get(normaliser_label(label), ())))

    def entrants(self, label: str) -> tuple[str, ...]:
        """Ids arrivant à `label` (exact normalisé, sans repli — BFS T3.4)."""
        return tuple(sorted(self._vers.get(normaliser_label(label), ())))

    def bouts(self, ident: str) -> tuple[str, str, str] | None:
        """`(src, dst, relation)` normalisés d'une arête, `None` si absente."""
        arete = self._aretes.get(ident)
        if arete is None:
            return None
        return (arete.src, arete.dst, arete.relation)

    def par_tier(self, niveau: str) -> tuple[str, ...]:
        """Ids des arêtes d'un tier (`high`, `medium`, `low`)."""
        return tuple(sorted(self._tiers.get(niveau, ())))

    def stats(self) -> dict[str, int]:
        """Tailles (observabilité `/status`, T5.9)."""
        return {
            "aretes": len(self._aretes),
            "labels": len(set(self._depuis) | set(self._vers)),
            "tokens": len(self._tokens),
            "relations": len(self._relations),
        }
