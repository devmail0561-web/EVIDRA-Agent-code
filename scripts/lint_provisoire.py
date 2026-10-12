#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Garde I9 : aucun nombre dépendant de B3/B4 en constante de code non déclarée.

Toute constante numérique module (`NOM_MAJ = <nombre>`) sous `src/evidra/`
doit figurer dans `REGISTRE` avec un statut :
- `version` : version de format, exempte (ex. `VERSION_SNAPSHOT`) ;
- `constate` : comportement moteur mesuré, avec référence (ex. plafonds) ;
- `spec` : valeur de spec/plan citée (ex. quarantaine après 3 échecs) ;
- `provisoire` : défaut toléré, surchargeable (directive/args), à calibrer.

Maille exacte (testée) : assignations module-niveau, cible unique
`NOM_MAJ`, valeur `int`/`float` littérale (ni `bool`, ni annotée
`X: int = …`, ni unaire `X = -1`, ni expression, ni classe/fonction).
Les défauts d'appel (`timeout_s=30.0`, `budget=16`) et les seuils lus
depuis la directive (`quality.seuils_tiers`) sont hors maille.

Ajouter une constante sans l'enregistrer (ou en changer la valeur sans
mettre à jour le registre) fait échouer la garde. Usage :
`python scripts/lint_provisoire.py [racine_src]`.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# (module, nom) → (valeur, statut, justification).
REGISTRE: dict[tuple[str, str], tuple[float | int, str, str]] = {
    ("memory.snapshot", "VERSION_SNAPSHOT"): (1, "version", "format de snapshot"),
    ("memory.sous_graphe", "PROFONDEUR_DEFAUT"): (2, "spec", "PLAN_SA T3.4, profondeur ≤ 2"),
    ("memory.sous_graphe", "MAX_NOEUDS"): (500, "constate", "oversize moteur > 500 nœuds"),
    ("memory.sous_graphe", "MAX_ARETES"): (2000, "constate", "oversize moteur > 2000 arêtes"),
    ("tools.report", "LIMITE_SECTION"): (100, "provisoire", "présentation, surchargeable"),
    ("tools.query_gaps", "PROFONDEUR_CHAINE"): (1, "provisoire", "chaîne surveillée, défaut"),
    ("kernel.registry", "SEUIL_QUARANTAINE"): (3, "spec", "PLAN_SA T1.3, 3 échecs ⇒ quarantaine"),
}

STATUTS = frozenset({"version", "constate", "spec", "provisoire"})


def constantes(racine: Path) -> dict[tuple[str, str], float | int]:
    """Constantes numériques module (`NOM = <nombre>`) trouvées sous `racine`."""
    trouvees: dict[tuple[str, str], float | int] = {}
    for chemin in sorted(racine.rglob("*.py")):
        module = ".".join(chemin.relative_to(racine).with_suffix("").parts)
        try:
            tree = ast.parse(chemin.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.isupper()
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, (int, float))
                and not isinstance(node.value.value, bool)
            ):
                trouvees[(module, node.targets[0].id)] = node.value.value
    return trouvees


def ecarts(racine: Path) -> list[str]:
    """Différences registre ↔ code (non déclarée, retirée, valeur dérivée)."""
    trouvees = constantes(racine)
    problemes = []
    for cle, valeur in sorted(trouvees.items()):
        if cle not in REGISTRE:
            problemes.append(f"constante non déclarée (I9) : {cle[0]}.{cle[1]} = {valeur!r}")
        elif REGISTRE[cle][0] != valeur:
            detail = f"{cle[0]}.{cle[1]} = {valeur!r}, registre = {REGISTRE[cle][0]!r}"
            problemes.append(f"valeur dérivée (I9) : {detail}")
        elif REGISTRE[cle][1] not in STATUTS:
            problemes.append(f"statut invalide (I9) : {cle[0]}.{cle[1]} = {REGISTRE[cle][1]!r}")
    for cle in sorted(REGISTRE):
        if cle not in trouvees:
            problemes.append(f"registre orphelin (I9) : {cle[0]}.{cle[1]}")
    return problemes


def main(argv: list[str]) -> int:
    racine = Path(argv[1]) if len(argv) > 1 else Path("src/evidra")
    problemes = ecarts(racine)
    for probleme in problemes:
        print(probleme)
    print(f"{len(REGISTRE)} constantes déclarées, {len(problemes)} écart(s)")
    return 1 if problemes else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
