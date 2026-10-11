# Evidra (SA) — agent causal autonome

Projet Python indépendant qui importe le moteur GCN (`gcn-core` + `gcn-python`)
comme bibliothèque. Le SA orchestre, persiste, décide, surveille et communique ;
le moteur extrait, raisonne et valide. Rien du SA n'entre dans le moteur.

* Spec : `docs/ETUDE_SA.md`
* Plan d'exécution : `docs/PLAN_SA.md` (phases 0–10, jalons J0–J10 bloquants)

## Démarrage (phase 0)

```sh
uv sync
uv run pytest
uv run evidra --help
```

Le moteur est une dépendance `path` éditable (`../projet_CNM/gcn-python`),
pinnée à la première release du moteur (cf. `docs/engine-compat.md` après T0.2).
