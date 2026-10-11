# ADR-0006 — Politique de sélection à règles, pas de LLM orchestrateur

- Date : 2026-10-11
- Statut : accepté
- Fonde : ETUDE_SA.md §1.3 / PLAN_SA.md §3.4 (T4.3)

## Contexte

L'agent choisit ses outils selon la situation et ses directives. Un LLM
planificateur serait non déterministe, non testable offline et contournerait
les permissions.

## Décision

Table priorité → condition → outil (6 niveaux P1–P6, §1.3 de l'étude),
évaluée dans l'ordre, un seul outil principal par niveau, séquentiel, avec
budgets et anti-famine. Module hors noyau (`src/evidra/policy.py`, I2).

## Conséquences

Politique testable sans moteur ni disque (T4.3) ; cycle sans condition =
aucun outil.

## Alternative rejetée

LLM planner / frameworks agents — indéterministe, non offline, non auditable.
