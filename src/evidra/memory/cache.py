# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Cache LRU à invalidation ciblée (T5.6) : requêtes répétées en O(1).

Clé `(mot, sens, epoque)` → ids (jamais de preuves : reconstruites fraîches,
toujours actuelles). Entrée enregistrée sous les tokens du mot ; arête
`(src, dst)` n'invalide que les clés touchant ses tokens (sur-invalidation
possible, sous-invalidation interdite). Taille bornée (LRU). `epoque` =
marqueur externe (ex. `param_epoch`, câblage ouvert avec ADR-0010) : époques
distinctes = entrées distinctes. Compteurs pour `/status` (T5.9).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Hashable


class CacheResultats:
    """Cache de résultats de requêtes par label (un par domaine, via `Memoire`)."""

    def __init__(self, taille_max: int | None = None) -> None:
        from evidra.directive.schema import cache_taille_max_defaut

        borne = cache_taille_max_defaut() if taille_max is None else taille_max
        if borne < 1:
            raise ValueError(f"taille_max >= 1 exigée : {taille_max}")
        self._taille_max = borne
        self._entrees: OrderedDict[tuple[str, str, Hashable], tuple[str, ...]] = OrderedDict()
        self._etiquettes: dict[str, set[tuple[str, str, Hashable]]] = {}
        self.hits = 0
        self.misses = 0
        self.invalidations = 0

    def lire(self, mot: str, sens: str, epoque: Hashable = 0) -> tuple[str, ...] | None:
        """Hit (LRU bumpé) ou `None` (miss compté)."""
        cle = (mot, sens, epoque)
        trouve = self._entrees.get(cle)
        if trouve is None:
            self.misses += 1
            return None
        self._entrees.move_to_end(cle)
        self.hits += 1
        return trouve

    def ecrire(self, mot: str, sens: str, resultat: tuple[str, ...], epoque: Hashable = 0) -> None:
        """Mémorise (évince LRU au-delà du plafond)."""
        cle = (mot, sens, epoque)
        if cle in self._entrees:
            self._entrees.move_to_end(cle)
        self._entrees[cle] = resultat
        for token in mot.split():
            self._etiquettes.setdefault(token, set()).add(cle)
        while len(self._entrees) > self._taille_max:
            vieille, _ = self._entrees.popitem(last=False)
            for token in vieille[0].split():
                porteuses = self._etiquettes.get(token)
                if porteuses is not None:
                    porteuses.discard(vieille)
                    if not porteuses:
                        del self._etiquettes[token]

    def invalider(self, *labels: str) -> int:
        """Invalide les entrées touchant ces labels ; retourne le compte."""
        tokens: set[str] = set()
        for label in labels:
            tokens.update(label.split())
        cles: set[tuple[str, str, Hashable]] = set()
        for token in tokens:
            cles |= self._etiquettes.get(token, set())
        for cle in cles:
            self._entrees.pop(cle, None)
            for token in cle[0].split():
                porteuses = self._etiquettes.get(token)
                if porteuses is not None:
                    porteuses.discard(cle)
                    if not porteuses:
                        del self._etiquettes[token]
        self.invalidations += len(cles)
        return len(cles)

    def vider(self) -> None:
        """Vide les entrées (rebuild) ; compteurs conservés (observabilité)."""
        self._entrees.clear()
        self._etiquettes.clear()

    def compteurs(self) -> dict[str, int]:
        """`hits/misses/invalidations` + taille (pour `/status`)."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "invalidations": self.invalidations,
            "taille": len(self._entrees),
        }
