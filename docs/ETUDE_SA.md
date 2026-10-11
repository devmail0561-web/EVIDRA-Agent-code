# ÉTUDE : Agent Evidra (SA) — Système Agentique GCN
## Architecture, vision et plan de développement

**Auteur** : Michel Tendeng  
**Date** : 2026-09-25  
**Statut** : Document de conception — projet futur, séparé du moteur  
**Périmètre** : SA uniquement. Ce projet n'existe pas encore. Il importe le moteur GCN (gcn-core + gcn-python) comme dépendance externe.

---

## Avertissement préliminaire

Ce document décrit un projet qui n'existe pas encore. Il ne décrit pas des extensions du moteur — il décrit un projet Python indépendant qui utilise le moteur comme bibliothèque. Toute capacité décrite ici doit être implémentée dans le codebase SA, jamais dans gcn-core ou gcn-python.

Ce document est un état de la vision architecturale et un plan de conception. Les affirmations sur le moteur (ce qu'il fait) sont fondées sur l'inspection directe du code source.

---

## Table des matières

1. [Nature du SA et séparation avec le moteur](#1-nature-du-sa-et-séparation-avec-le-moteur)
2. [La contrainte fondamentale : les CIRs ont des sources](#2-la-contrainte-fondamentale--les-cirs-ont-des-sources)
3. [Le paradigme agentique](#3-le-paradigme-agentique)
4. [Pourquoi le moteur seul ne suffit pas](#4-pourquoi-le-moteur-seul-ne-suffit-pas)
5. [Vision : l'agent Evidra](#5-vision--lagent-evidra)
6. [Architecture de la mémoire agentique](#6-architecture-de-la-mémoire-agentique)
7. [Optimisation des recherches et du raisonnement sur les graphes](#7-optimisation-des-recherches-et-du-raisonnement-sur-les-graphes)
8. [Communication et protocoles](#8-communication-et-protocoles)
9. [Directives et objectifs](#9-directives-et-objectifs)
10. [Analyse des écarts (Gap Analysis — SA)](#10-analyse-des-écarts-gap-analysis--sa)
11. [Architecture cible](#11-architecture-cible)
12. [Priorités de développement](#12-priorités-de-développement)

---

## 1. Nature du SA et séparation avec le moteur

### 1.1 Distinction structurelle

Le **SA (Agent Evidra)** est un **projet et un package séparés** — il n'est pas dans gcn-core, ni dans gcn-python, ni dans gcn-tools. C'est un nouveau projet Python indépendant qui importe gcn-python comme dépendance et invoque le moteur via son API. Il orchestre, persiste, décide, communique. Le moteur est son outil principal — pas son équivalent, pas sa couche interne.

Cette séparation est structurelle et non négociable :
- Le moteur (gcn-core + gcn-python) est une **bibliothèque** : elle est invoquée, elle produit un résultat, elle s'arrête. Elle n'a pas d'état persistant, pas de boucle, pas d'opinion sur les sources.
- Le SA est une **application/service** : il tourne en boucle, maintient un état persistant (le graphe de connaissance), prend des décisions autonomes selon des directives, et expose une API.

Toute capacité qui relève de l'orchestration, de la persistance ou de la communication appartient au SA. Elle ne doit jamais entrer dans le moteur.

### 1.2 Ce que le moteur fait (résumé)

Le moteur fait exactement trois choses, et rien d'autre :

1. **Extraire des CIRs** depuis du texte (FR/EN) ou du code, par voie symbolique (Rust) ou par apprentissage (Python)
2. **Raisonner causalement** sur un graphe CIR donné (Pearl 1–3, BFS, CYCLES, GAPS)
3. **Valider** l'intégrité structurelle d'un CIR (arêtes pendantes, boucles réflexives, nœuds orphelins, labels vides, confiance faible — les types de nœuds et relations sont enforced au parse-time par le Rust enum, pas à la validation runtime)


### 1.3 Nature de l'agent : mémoire = intelligence, graphes = connaissance

**La mémoire est l'intelligence de l'agent.** Ce n'est pas un stockage — c'est le fondement de ce qu'il est capable de faire. Un agent dont la mémoire est bien organisée, avec des sources évaluées et une connaissance catégorisée par domaine et pertinence, surpasse un agent dont la mémoire est un tas indifférencié, même si les deux partagent le même moteur de raisonnement.

**Les graphes causaux sont sa connaissance.** Pas des fichiers de données, pas des logs — des structures qui représentent comment les choses s'influencent dans son domaine, avec les preuves à l'appui.

L'agent n'est **pas un pipeline hardcodé**. Il ne suit pas une séquence fixe PERCEVOIR→RAISONNER→AGIR câblée dans le code. C'est un raisonneur qui dispose d'un ensemble d'**outils** et d'une **mémoire de connaissance persistante**, et qui décide à chaque cycle quels outils invoquer selon la situation courante et ses directives.

**Les outils** sont les primitives d'action de l'agent. Chaque outil a une interface définie, est interchangeable, et peut être étendu sans modifier la logique agentique centrale. Exemples :

| Outil | Ce qu'il fait |
|---|---|
| `extract(text, source)` | Appelle le moteur → produit un CIR avec provenance |
| `ingest(cir)` | Intègre un CIR dans la mémoire de connaissance |
| `query_causes(concept)` | Interroge la mémoire → causes sourcées |
| `query_effects(concept)` | Interroge la mémoire → effets sourcés |
| `query_chain(a, b)` | Chemin causal entre deux concepts |
| `query_cycles()` | Cycles dans le graphe courant |
| `query_gaps(chain)` | Lacunes dans une chaîne surveillée |
| `validate(claim)` | Confronte un claim à la mémoire → verdict sourcé |
| `alert(condition, payload)` | Émet une alerte structurée |
| `report(scope, format)` | Produit un rapport depuis la mémoire |
| `fetch(adapter, config)` | Récupère des données via un adaptateur externe |
| `counterfactual(concept)` | Pearl do-calculus sur la mémoire |

L'agent choisit ses outils selon une **politique de sélection à règles** — pas un LLM orchestrateur, pas une séquence fixe. Les règles sont évaluées dans l'ordre de priorité décroissante à chaque début de cycle :

| Priorité | Condition | Outils déclenchés |
|---|---|---|
| 1 (urgence) | Alerte de monitoring active | `alert()` → `report()` |
| 2 (requête entrante) | Claim externe reçu | `validate()` |
| 3 (requête causale) | Question causale reçue | `query_causes()` / `query_chain()` / etc. |
| 4 (nouvelles données) | Adaptateur a produit des données | `fetch()` → `extract()` → `ingest()` |
| 5 (maintenance) | Relations STALE détectées | décroissance, révision |
| 6 (analyse) | Cycle de fond | `query_cycles()` → `query_gaps()` si domaine surveillé |
| — (rien) | Aucune condition | aucun outil — cycle no-op |

Les priorités 1–3 sont déclenchées par événement extérieur (push). Les priorités 4–6 sont déclenchées par l'agent lui-même selon l'horloge et l'état de la mémoire (pull). La directive définit quels niveaux sont actifs et à quelle fréquence.

**Règle anti-famine** : une priorité stricte rendrait P5/P6 (maintenance, fond) inaccessibles si P4 (flux de données) est saturé en continu. La solution est un **budget par cycle** défini dans la directive : P1–P3 consomment leur quota au-delà duquel P4–P6 sont garantis un slot minimum par cycle, indépendamment du flux entrant.

**Conflit multi-conditions** : si plusieurs conditions de niveaux différents sont vraies au même cycle (exemple : claim entrant P2 + nouvelles données P4), les conditions sont traitées **séquentiellement dans l'ordre de priorité**, pas en parallèle. Un seul outil principal par tick de priorité. Cela simplifie l'état et évite les effets de bord inter-outils dans un même cycle.

Un cycle où aucune condition n'est vraie ne déclenche aucun outil.

**La mémoire de connaissance** est le graphe causal persistant. Elle n'est pas une session — elle n'est jamais réinitialisée entre deux cycles, entre deux tâches, entre deux redémarrages de l'agent. Elle accumule la connaissance causale extraite de toutes les sources analysées, avec provenance complète, et son contenu vieillit et évolue selon le cycle de vie des relations.

### 1.4 Responsabilités du SA

Le SA encapsule la logique de sélection des outils, la mémoire de connaissance, et l'interprétation des directives :

- **Mémoire de connaissance** : graphe causal persistant, indexé, avec cycle de vie
- **Registre d'outils** : liste des outils disponibles, leurs interfaces, leurs dépendances
- **Boucle de raisonnement** : à chaque cycle, évaluer la situation et sélectionner les outils appropriés
- **Directives** : objectifs, domaines, seuils, actions autorisées — ce qui guide la sélection des outils
- **Registre d'adaptateurs** : composants interchangeables pour les sources externes

### 1.5 Ce que cette distinction interdit

- Ajouter une boucle d'ingestion continue **dans** le moteur → appartient au SA
- Implémenter la décroissance temporelle **dans** `CausalGraph` → appartient au SA
- Exposer une API HTTP **depuis** gcn-python directement → appartient au SA
- Gérer des directives **dans** le moteur → appartient au SA

**Exception licite** : étendre le format CIR pour inclure la provenance (ref, span, méthode, timestamp) est une modification du moteur, car le CIR est la frontière entre le noyau et le reste du système. Tout ce qui traverse cette frontière doit être défini dans le noyau.

---

## 2. La contrainte fondamentale : les CIRs ont des sources

### 2.1 La règle

Un CIR ne peut pas être inventé. Chaque nœud et chaque arête d'un CIR doit être tracé vers une source vérifiable : un document, une URL, un fichier de code, une ligne de log. C'est cette propriété qui distingue GCN d'un LLM générant des relations causales probables — GCN prouve, le LLM opine. **Borné 2026-10-11** : le graphe stocke des **assertions sourcées**, pas des faits — Pearl et le counterfactual s'y appliquent comme calculs sur assertions citées (avec preuves), sans contrôle de confondeurs ni modèle structurel ; tout counterfactual est étiqueté comme tel, jamais présenté comme fait établi.

Cette règle s'applique à tous les acteurs du système : le moteur symbolique, le modèle ML, l'annotateur, et tout agent utilisant GCN. Aucun agent ne peut écrire dans le graphe causal sans référencer une source.

### 2.2 Ce que ça implique pour l'architecture du SA

**Pour l'ingestion** : l'agent ne peut pas créer de CIRs. Il ne peut qu'extraire des CIRs depuis des sources qu'il a analysées. Toute écriture dans le graphe est une extraction, jamais une déduction libre.

**Pour le raisonnement** : les relations déduites (A → C déduit de A → B et B → C) sont licites, mais elles doivent être marquées `derivation: "derived"` avec les deux sources qui les justifient. Les déductions sont des inférences tracées, pas des inventions.

**Pour la validation** : quand l'agent reçoit un claim d'un LLM ou d'un humain, il doit trouver la source dans le graphe pour répondre CONFIRMÉ. S'il ne trouve pas de source, il répond NON CONFIRMÉ — pas FAUX. L'absence de preuve n'est pas une preuve d'absence.

**Pour la communication** : toute sortie de l'agent incluant une affirmation causale doit inclure la source. Émettre "A cause B" sans citation est une violation du contrat de traçabilité.

### 2.3 Ce que ça interdit au SA

- Un agent ne peut pas "synthétiser" des relations causales depuis plusieurs CIRs sans tracer la déduction
- Un agent ne peut pas augmenter la confiance d'une relation par inférence libre — seulement par re-confirmation depuis de nouvelles sources
- Un agent ne peut pas supprimer une relation du graphe sans tracer la raison (source invalide, contradiction arbitrée)

---

## 3. Le paradigme agentique

### 3.1 Définition opérationnelle d'un agent

Un agent est un système qui, de façon continue et autonome :
- **Perçoit** son environnement (données entrantes, événements, sorties d'autres agents)
- **Maintient un modèle interne** de l'état du monde dans son domaine
- **Raisonne** sur ce modèle pour comprendre la situation actuelle
- **Planifie** les actions appropriées compte tenu de ses objectifs
- **Agit** — émet des sorties, déclenche des processus, communique avec d'autres agents
- **Apprend** — met à jour son modèle à partir des nouvelles informations et des résultats de ses actions
- **Sait quand s'abstenir** — reconnaît les situations où ses informations sont insuffisantes pour agir de façon fiable

Un agent n'est pas un outil amélioré. C'est un paradigme différent : autonomie, continuité, orientation par objectifs.

### 3.2 Ce que le paradigme agentique change pour GCN

Dans le paradigme actuel (outil) :
- L'humain lance une commande
- Le moteur analyse et répond
- La session se termine

Dans le paradigme agentique :
- L'agent surveille des flux de données définis
- Il extrait et intègre en continu des CIRs dans son modèle du monde
- Il détecte des conditions (nouvelles chaînes, conflits, gaps critiques, cycles)
- Il agit sur ces conditions sans attendre une requête (alerte, validation, rapport)
- Il gère son propre état entre les cycles (connaissance fraîche, connaissance stale, conflits non résolus)
- Il communique avec d'autres agents ou systèmes via des protocoles définis

### 3.3 Le modèle du monde

Dans un agent GCN, le graphe causal est le **modèle du monde**. Ce n'est pas une base de données — c'est la représentation structurée de comment les choses s'influencent dans le domaine de l'agent. Tout ce que l'agent perçoit, il l'intègre dans ce modèle. Tout ce qu'il dit en sort.

Ce modèle du monde doit être :
- **Vivant** : mis à jour en continu au fil des nouvelles observations
- **Temporel** : les relations vieillissent, se confirment ou s'affaiblissent avec le temps
- **Conflictuel** : capable de représenter des contradictions entre sources sans les effacer
- **Hiérarchique** : capable de représenter des causalités à plusieurs niveaux d'abstraction
- **Borgné** : l'agent sait ce que son modèle ne contient pas, pas seulement ce qu'il contient

---

## 4. Pourquoi le moteur seul ne suffit pas

### 4.1 Absence de communication et de protocoles

Le moteur n'expose qu'une interface CLI. Il n'y a pas d'API HTTP, pas de protocole inter-agents, pas de format de sortie adaptatif. Pour qu'un LLM consomme le résultat d'une requête, il faut un pont manuel. Pour que deux instances du moteur coopèrent, il n'existe aucun protocole défini.

Cette limite empêche toute intégration native dans un système multi-agents, un pipeline RAG, ou un service de validation en temps réel.

### 4.2 Absence de directive et d'objectifs

Le moteur n'a aucune notion de mission, de domaine de surveillance, de seuil d'alerte, ou d'action autorisée. Il traite toutes les requêtes avec la même priorité, il ne sait pas ce qu'il cherche, et il n'agit jamais spontanément. Sans directive, il ne peut pas être autonome — même avec tous les raisonnements du monde, il ne saurait pas quand ni pourquoi les appliquer.

### 4.3 Absence de boucle agentique

Le moteur est invoqué, il produit un résultat, il s'arrête. Il n'y a pas de boucle PERCEVOIR → RAISONNER → PLANIFIER → AGIR → METTRE À JOUR. Entre deux invocations, il n'existe pas. Cette propriété est la conséquence directe du paradigme CLI interactif dans lequel il a été conçu, et c'est la limite la plus fondamentale pour un usage agentique.

---

## 5. Vision : l'agent Evidra

### 5.1 Pourquoi "Evidra"

Evidra, dans la mythologie grecque, est le messager des dieux, guide des âmes, dieu des transitions et de la communication. Il connaît les deux mondes, se déplace entre eux, transmet l'information avec précision et rapidité. Il sait quoi dire, à qui, quand — et quand se taire.

Pour GCN, "Evidra" désigne un agent qui :
- Connaît son domaine en profondeur (le graphe causal comme modèle du monde)
- Se déplace entre les niveaux d'abstraction (micro, méso, macro)
- Transmet l'information dans le format adapté à chaque destinataire
- Agit au bon moment, avec la bonne précision, sur la bonne cible
- Reconnaît les limites de son savoir et les communique explicitement

Ce n'est pas un objectif poétique — c'est une spécification fonctionnelle.

### 5.2 Profil de l'agent Evidra

| Propriété | Comportement attendu |
|---|---|
| Autonomie | Agit sans attendre une requête humaine |
| Continuité | Tourne en boucle, pas en mode one-shot |
| Orientation | Guidé par des directives explicites (domaine, objectifs, seuils) |
| Traçabilité | Chaque affirmation cite sa source |
| Honnêteté | Distingue ce qu'il sait, ce qu'il infère, et ce qu'il ignore |
| Adaptabilité | Format de sortie selon le destinataire |
| Sobriété | N'agit que quand c'est justifié |

### 5.3 Rôles de l'agent

L'agent Evidra remplit quatre rôles fondamentaux qui sont indépendants du domaine applicatif :

**Rôle 1 : Accumulateur intelligent**
Il ingère des sources, extrait des CIRs, les intègre dans le graphe. Il ne fait pas que stocker — il évalue chaque CIR entrant : est-ce cohérent avec ce que le graphe contient déjà ? Est-ce une confirmation, une contradiction, ou une nouvelle information ? Il filtre le bruit. Il refuse les CIRs qui ne passent pas les seuils de qualité définis dans ses directives.

Ce rôle est le seul à écrire dans le graphe. Les trois autres lisent.

**Rôle 2 : Raisonneur**
Il répond aux questions causales sur le graphe avec preuves citées. Il raisonne à plusieurs niveaux. Il sait quand son graphe n'est pas assez dense pour répondre de façon fiable, et le dit.

**Rôle 3 : Validateur**
Il reçoit un claim externe (d'un LLM, d'un humain, d'un autre agent) et retourne un verdict structuré :
- `CONFIRMED` : relation présente dans le graphe, source citée, confiance X
- `UNCONFIRMED` : relation absente du graphe — pas de preuve, pas de réfutation
- `CONTRADICTED` : le graphe contient une relation opposée, source citée, confiance Y. **Opérationnalisé 2026-10-11** : table fermée des paires opposées (ex. `causes`/`prevents`, `enables`/`blocks`, affirmation vs négation explicite du même lien) + granularité (le plus spécifique l'emporte à confiance égale) ; hors table = `UNCONFIRMED`, jamais `CONTRADICTED` par défaut.

Ce rôle est la pièce la plus différenciante du système. C'est là que GCN devient une couche de preuve pour les LLMs.

**Rôle 4 : Moniteur**
Il surveille le graphe en continu et déclenche des alertes sur des conditions définies dans ses directives : nouveau CYCLE dans un domaine critique, GAPS dans une chaîne surveillée, relation haute-confiance invalidée, source fiable qui contredit une croyance établie. Il agit sur événement, pas sur requête.

### 5.4 Ce que l'agent fait avec ce qu'il sait

Un agent qui accumule sans agir est une base de données muette. Voici les opérations que l'agent Evidra doit effectuer sur sa connaissance :

**Arbitrage des conflits** : quand deux sources produisent des relations contradictoires sur la même paire, l'agent ne les accumule pas silencieusement. Il calcule un score de confiance composite pour chaque version et élit la dominante. La formule d'arbitrage est détaillée en §6.8.

**Décroissance temporelle** : la confiance d'une relation décroît si elle n'est pas re-confirmée périodiquement. La décroissance est paramétrable dans les directives (domaine CTI : décroissance rapide, domaine droit : décroissance lente). Une relation non vue depuis N jours passe à l'état "stale" avant d'être marquée pour révision.

**Déduction tracée** : si A → B et B → C sont dans le graphe et que A → C ne l'est pas, l'agent peut inférer A → C avec `derivation: "derived"`, confiance = min(conf(A→B), conf(B→C)), et les deux arêtes sources comme justification.

**Détection des lacunes orientée objectif** : le moteur détecte les GAPS structurels. L'agent Evidra détecte les lacunes **par rapport à ses objectifs** — une chaîne incomplète dans un domaine surveillé est plus urgente qu'un nœud orphelin dans un domaine hors scope. Il formule la question : "pour compléter la chaîne entre X et Y, quelles sources dois-je acquérir ?"

**Déduplication sémantique** : deux nœuds avec des labels différents mais référant au même concept ("authentification", "auth", "login") doivent être fusionnés ou liés. Ce n'est pas un problème trivial — il nécessite une résolution d'entités.

---

## 6. Architecture de la mémoire agentique

### 6.1 La mémoire est l'intelligence

La mémoire de l'agent n'est pas un stockage passif. C'est le siège de son intelligence. Ce qu'il sait, comment il l'a organisé, la confiance qu'il accorde à chaque source, la pertinence qu'il attribue à chaque relation — tout cela constitue ce qu'il est capable de faire.

Un agent avec une mémoire mal organisée produit des réponses de mauvaise qualité même avec le meilleur moteur de raisonnement. Un agent avec une mémoire bien organisée peut répondre correctement avec un raisonnement minimal.

La métaphore juste est celle du **bibliothécaire** : il ne se contente pas de stocker des livres, il les classe par domaine, par pertinence, par auteur, par fiabilité de l'éditeur. Il sait où chercher, il sait quoi croire, il sait quand une source est douteuse. Sa valeur n'est pas dans le nombre de livres qu'il possède — c'est dans la qualité de son organisation et de son jugement sur les sources.

### 6.2 Organisation de la connaissance : le modèle bibliothécaire

La connaissance n'est pas un graphe plat. Elle est organisée selon trois dimensions :

**Dimension 1 — Domaine**
Chaque relation appartient à un domaine (cybersécurité, conformité, recherche, code, droit, finance…) et à un sous-domaine. Le domaine est assigné à l'ingestion selon la directive active. Les graphes sont partitionnés par domaine — une requête dans le domaine CTI ne traverse pas le graphe conformité.

**Dimension 2 — Pertinence**
Au sein d'un domaine, les relations ne sont pas équivalentes. La pertinence combine :
- Le statut dans le cycle de vie (CONFIRMÉE > ACTIVE > NOUVELLE)
- Le nombre de sources indépendantes qui la confirment
- La centralité dans les chaînes du domaine (une relation sur un chemin critique est plus pertinente qu'un nœud feuille)
- La fraîcheur (une relation récente est plus pertinente dans les domaines à évolution rapide)

**Dimension 3 — Source**
Chaque relation est rattachée à sa source avec provenance complète. Les sources ne sont pas toutes équivalentes — leur fiabilité est évaluée et mise à jour en continu par la mémoire elle-même.

### 6.3 Le registre de sources : l'intelligence sur les sources

La mémoire maintient un **registre de sources** — une évaluation de fiabilité construite depuis l'expérience accumulée, jamais déclarée à la main.

Pour chaque source connue, le registre tient :

```json
{
  "source_uri": "https://nvd.nist.gov/feeds/json/cve/",
  "domain": "cybersecurity_cti",
  "first_seen": "2026-01-15T10:00:00Z",
  "last_seen": "2026-09-25T08:00:00Z",
  "extraction_method": "symbolic_rust",
  "relations_contributed": 847,
  "confirmed_by_independent_source": 731,
  "contradicted_by_higher_confidence": 12,
  "confirmation_rate": 0.863,
  "contradiction_rate": 0.014,
  "reliability_score": 0.849,
  "status": "trusted"
}
```

Le `reliability_score` n'est pas déclaré — il est calculé depuis les données accumulées. Une source qui contribue des relations systématiquement confirmées par d'autres sources indépendantes gagne en fiabilité. Une source dont les relations sont fréquemment contredites perd en fiabilité. Ce processus est continu et automatique.

**Les statuts de fiabilité** :
- `trusted` : confirmation_rate ≥ 0.80, contradiction_rate ≤ 0.05
- `monitored` : confirmation_rate entre 0.60 et 0.80 — acceptée avec pondération réduite
- `suspect` : contradiction_rate > 0.10 — signalée, relations admises en NOUVELLE seulement
- `blocked` : exclue explicitement par directive ou après audit manuel

**Ce que le registre permet** :
- Pondérer la confiance initiale d'un CIR par la fiabilité de sa source
- Alerter quand une source fiable produit soudainement des relations contradictoires (signal d'anomalie)
- Répondre à la question "d'où vient cette information et est-elle fiable ?" avec un score fondé sur l'historique
- Identifier les sources de référence dans un domaine (les sources les plus confirmées)

### 6.4 Principes d'organisation

1. **Partitionnement par domaine** : graphes distincts par domaine, requêtes ciblées
2. **Écriture incrémentale** : WAL — chaque nouvelle relation s'ajoute sans réécrire l'ensemble
3. **Vieillissement** : la confiance décroît pour les relations non re-confirmées
4. **Résolution de conflits** : les contradictions sont arbitrées par fiabilité de source + fréquence de confirmation
5. **Accessibilité indexée** : index inversé sur labels, index par domaine, index de pertinence
6. **Registre de sources actif** : fiabilité mise à jour en continu depuis l'expérience accumulée

### 6.5 Structure de persistance recommandée : WAL + index

**Write-Ahead Log (WAL)** pour le graphe :
- `graph_base.json` : dernier snapshot compact (réécrit uniquement lors d'une compaction explicite)
- `graph_delta.jsonl` : nouvelles arêtes depuis le dernier snapshot (append-only, une ligne JSON par CIR)
- Chargement = `graph_base.json` + replay de `graph_delta.jsonl`
- Compaction = fusion delta dans base + truncation du delta (déclenchée sur `/save` ou sur seuil de taille)

Coût d'écriture par item : O(1) — une ligne JSON. Coût de lecture : O(n_delta) pour le replay, puis O(1) avec index.

**Index inversé sur labels** :
```
label_index: dict[str, list[node_id]]
```
Construit une seule fois après chargement, mis à jour à chaque insertion. Réduit `find_causes` et `find_effects` de O(n_edges) à O(k) où k est le nombre d'arêtes adjacentes au nœud trouvé.

**Vecteurs par fichier individuel** :
Remplacer `session_vecs.npz` (réécriture complète) par un répertoire `vecs/` avec un fichier `.npy` par vecteur, nommé par clé stable (`sha256(texte) + "_" + position`). Le manifest reste un JSONL append-only.

### 6.6 Cycle de vie de la connaissance

Chaque relation dans le graphe traverse les états suivants :

```
NOUVELLE → ACTIVE → CONFIRMÉE (multi-sources) → STALE (non re-confirmée) → EN RÉVISION → [MAINTENUE | INVALIDÉE]
```

- **NOUVELLE** : extraite d'une seule source, confiance = confiance d'extraction
- **ACTIVE** : vue dans au moins 2 sources concordantes, confiance élevée
- **CONFIRMÉE** : vue dans N ≥ seuil sources, confiance maximale dans le domaine
- **STALE** : non re-confirmée depuis T jours (T défini dans les directives), confiance décroissante
- **EN RÉVISION** : contradite par une source récente, arbitrage en cours
- **MAINTENUE** : contradiction résolue en faveur de la relation originale
- **INVALIDÉE** : contradiction résolue en faveur de la nouvelle source, relation retirée

### 6.7 Provenance dans l'arête enrichie SA

L'arête dans la mémoire du SA enveloppe le CIR-noyau (immuable, produit par le moteur) et y ajoute l'état dynamique géré par le SA.

Exemple d'arête enrichie complète :

```json
{
  "source": "n001",
  "target": "n002",
  "relation": "cause",
  "attributes": {
    "confidence": 0.87,
    "explicit": true,
    "negated": false
  },
  "provenance": {
    "ref": "/home/michel/docs/rapport.pdf",
    "span": [10240, 10287],
    "extraction_method": "symbolic_rust",
    "model_version": "gcn-core-2.5.0",
    "extracted_at": "2026-09-25T14:32:00Z"
  },
  "status": "ACTIVE",
  "confirmation_count": 3,
  "last_confirmed_at": "2026-09-25T14:32:00Z",
  "source_reliability": 0.849
}
```

`ref` est un pointeur vers le document source (chemin, URL, identifiant) — GCN ne possède pas le document. `span` localise l'extrait dans le document : `TokenSpan{start,end}` pour le texte naturel, `CodeSpan{file,line_start,line_end}` pour le code, `Synthetic` pour les relations déduites sans ancrage physique (node.rs:71–83). La phrase source n'est **pas** stockée — ce serait dupliquer le document entier relation par relation.

Les 5 champs de provenance (`ref`, `span`, `extraction_method`, `model_version`, `extracted_at`) sont **immuables** — ils décrivent le fait d'observation ponctuel et sont définis dans le CIR-noyau. Les champs `status`, `confirmation_count`, `last_confirmed_at`, `source_reliability` sont **mutables** — gérés par le SA et jamais écrits dans le CIR-noyau.

### 6.8 Frontière CIR-noyau vs arête enrichie SA

**C'est le point d'architecture le plus délicat.**

Le CIR produit par le moteur est **immuable**. Il contient uniquement ce que l'extraction a observé au moment de l'analyse : la relation, les nœuds, les attributs, et la provenance statique. Ces champs ne changent jamais — ils décrivent un fait d'observation ponctuel.

L'arête stockée dans la mémoire de connaissance du SA est **mutable**. Elle enveloppe le CIR-noyau et y ajoute l'état dynamique géré par le SA.

La distinction est la suivante :

```
CIR-noyau (produit par le moteur, immuable)
┌────────────────────────────────────────────────────┐
│ source, target, relation, confidence               │
│ provenance:                                        │
│   ref               ← pointeur document, immuable  │
│   span              ← TokenSpan/CodeSpan/Synthetic, immuable │
│   extraction_method ← comment, immuable            │
│   model_version     ← quelle version, immuable     │
│   extracted_at      ← quand, immuable              │
└────────────────────────────────────────────────────┘

Arête enrichie SA (gérée par la mémoire, mutable)
┌────────────────────────────────────────────────────┐
│ cir: <CIR-noyau ci-dessus>                        │
│ status: NOUVELLE | ACTIVE | CONFIRMÉE | ...        │ ← SA
│ confirmation_count: 7                              │ ← SA
│ last_confirmed_at: 2026-09-25T...                  │ ← SA
│ source_reliability: 0.849                          │ ← SA (depuis registre)
└────────────────────────────────────────────────────┘
```

**Règle** : le moteur ne reçoit jamais l'arête enrichie — il ne connaît que le CIR-noyau. La mémoire de connaissance ne modifie jamais le CIR-noyau — elle le stocke tel quel et gère l'état mutable en dehors. Ce sont deux objets distincts avec des cycles de vie distincts.

### 6.9 Formule d'arbitrage des conflits

Quand deux arêtes concurrentes A et B décrivent la même paire (src, dst) avec des relations différentes ou des confiances contradictoires, le SA calcule un **score composite** pour chacune :

```
score(arête) = conf_extraction
             × reliability(source)
             × norm_conf(confirmations)
             × freshness(last_confirmed_at)
```

Où :
- `conf_extraction` ∈ [0,1] : confiance produite par l'extraction (CIR-noyau, immuable)
- `reliability(source)` ∈ [0,1] : score du registre de sources (calculé depuis l'historique)
- `norm_conf(n)` = `log₂(1 + n) / log₂(1 + Nmax)` : bonus logarithmique normalisé ∈ [0,1]. Nmax est la valeur de saturation définie dans la directive (défaut : 50). Base 2 pour lisibilité. Une relation à 1 confirmation obtient log₂(2)/log₂(51) ≈ 0.18 — voulu : une seule confirmation ne suffit pas à dominer.
- `freshness(t)` = `exp(-(now - t) / T_domaine)` : décroissance exponentielle depuis la dernière confirmation. T_domaine est la **constante de temps** de la confiance dans ce domaine (vraie demi-vie = T·ln2 ≈ 0.693·T), définie dans la directive (défauts : T=7j CTI, T=90j conformité, T=365j droit). **Corrigé 2026-10-11** : t = `published_at` du document source (extrait par l'adaptateur : frontmatter/RSS/file-mtime, sinon `unknown` → fraîcheur neutre 1.0 + flag), jamais la date d'ingestion — ré-ingérer un vieux rapport ne rajeunit plus une connaissance périmée. « Non re-vu » signale une revérification à faire (STALE), il n'abaisse pas la vérité : péremption ≠ réfutation.

Le score est donc toujours ∈ [0,1] et interprétable comme un score de confiance composite.

**Règle de quorum** : si `score(A) / score(B) > seuil_quorum`, A l'emporte. Le seuil par défaut est 2.0 — **valeur à calibrer empiriquement sur corpus annoté avant mise en production**, non fondée théoriquement. Si le ratio est inférieur au seuil, le conflit reste EN RÉVISION.

**Exemple** (Nmax=50, T_domaine=7j, âge arête B = 0j) :
- Arête A : `symbolic_rust`, conf 0.90, reliability 0.85, 1 confirmation → norm=log₂(2)/log₂(51)≈0.18 → score = 0.90 × 0.85 × 0.18 × 1.0 ≈ **0.135**
- Arête B : `ml_python`, conf 0.60, reliability 0.72, 15 confirmations → norm=log₂(16)/log₂(51)≈0.70 → score = 0.60 × 0.72 × 0.70 × 1.0 ≈ **0.302**

ratio = 0.302/0.135 ≈ 2.24 > 2.0 → B l'emporte. Le consensus de 15 confirmations bat l'extraction symbolique isolée.

---

## 7. Optimisation des recherches et du raisonnement sur les graphes

### 7.1 Problème de fond — état actuel du moteur

Toutes les opérations de la mémoire de connaissance actuelle sont O(n_edges) :

| Opération | Implémentation actuelle | Coût |
|---|---|---|
| `find_causes(keyword)` | Scan linéaire, correspondance 4 niveaux (exact → normalisé → word-boundary → substring) sur tous les labels (instructions.py:175–187) | O(n_edges) |
| `find_effects(keyword)` | Idem | O(n_edges) |
| `find_path(a, b)` | BFS non pondéré — chemin le plus court en sauts | O(V + E) |
| `CYCLES?` | **Rust CLI uniquement** — résultat pré-calculé par le middleend ; non disponible dans la mémoire Python actuelle. Coût query-time = O(\|cycles\|) | — |
| `GAPS?` | **Rust CLI uniquement** — filtre `temporal_gap.is_some()` + `unresolved.len()>0` (query.rs:190–204) ; non disponible dans la mémoire Python actuelle | — |

Sur un graphe de 100 000 arêtes — objectif réaliste pour un domaine CTI actif — chaque requête lit 100 000 entrées. Ce n'est pas acceptable en production, ni pour un agent en boucle continue.

De plus, le BFS retenait le chemin **le plus court en sauts**, pas le chemin **le plus fiable**. Un chemin A→B→C→D à 0.90 de confiance par arête (confiance finale 0.73) est meilleur qu'un chemin direct A→D à 0.60. **Corrigé côté moteur (Phase 3, 2026-10-08, `CHANGELOG:59-64`)** : `CHAIN` = Dijkstra confiance-max (coût `−ln(conf)`, Yen top-k, `pearl.rs:chain_topk`) ; le BFS ne subsiste qu'en résiduel/temporel. Reste côté SA : exposer `query_chain` en coquille mince sur `reason()`, sans réimplémenter Dijkstra.

### 7.2 Recommandation — quatre optimisations dans l'ordre

Les optimisations sont présentées dans l'ordre où elles doivent être implémentées. Chacune est indépendante de la suivante, mais chacune maximise l'impact des suivantes.

---

**Optimisation 1 — Partitionnement par domaine** *(priorité absolue)*

C'est la décision architecturale qui conditionne tout le reste. La mémoire de connaissance n'est pas un graphe global unique — c'est un ensemble de graphes partitionnés par domaine.

```
mémoire/
  domaines/
    cybersecurity_cti/    ← graphe CTI isolé
    conformite_rgpd/      ← graphe conformité isolé
    code_audit/           ← graphe code isolé
  registre_sources.json   ← partagé entre domaines
```

Une requête dans le domaine CTI ne traverse jamais le graphe conformité. Un graphe de 100 000 arêtes réparti en 10 domaines = 10 graphes de 10 000 arêtes. Toutes les optimisations suivantes opèrent sur le graphe de domaine, pas sur le graphe global — leur gain est donc multiplié par le facteur de partitionnement.

**Coût d'implémentation** : faible — structure de répertoires + routage des requêtes par domaine.  
**Impact** : multiplicatif sur toutes les opérations suivantes.

---

**Optimisation 2 — Index inversé sur labels** *(vitesse)*

Toute requête commence par retrouver un nœud par son label. C'est le bottleneck de chaque opération. L'index inversé élimine le scan linéaire.

```
label_index:  dict[str, list[node_id]]   ← mot complet
tokens_index: dict[str, list[node_id]]   ← tokens individuels pour match partiel
```

Construction O(n_nodes) une seule fois à l'initialisation. Mise à jour O(1) à chaque insertion. `find_causes("ransomware")` passe de O(n_edges) à O(k) où k est le nombre d'arêtes adjacentes au nœud trouvé — typiquement quelques dizaines, jamais des milliers.

Index complémentaires à construire simultanément :

```
domain_index:    dict[domain, set[edge_id]]
relation_index:  dict[RelationType, list[edge_id]]
confidence_tiers: dict[str, list[edge_id]]       ← "high"≥0.85, "medium"≥0.65, "low"<0.65
```

**Coût d'implémentation** : faible.  
**Impact** : immédiat sur toutes les requêtes — gain typique ×10 à ×1000 selon la taille du graphe.

---

**Optimisation 3 — Dijkstra avec poids `-log(confidence)`** *(qualité du raisonnement)*

C'est la seule optimisation qui améliore la **qualité** des réponses, pas seulement leur vitesse.

**Problème (résolu côté moteur Phase 3, 2026-10-08)** : le BFS trouvait le chemin le plus court en nombre de sauts, pas le plus fiable. Le moteur fait désormais Dijkstra confiance-max (`CHANGELOG:59-64`) ; reste côté SA : exposer `query_chain` + trancher Dijkstra vs BFS bidirectionnel pour les chemins longs.

**Principe** : la confiance d'un chemin se propage multiplicativement.

```
conf(A → B → C) = conf(A→B) × conf(B→C)
```

Un chemin de 3 arêtes à 0.90 chacune (conf finale 0.73) est plus fiable qu'un chemin direct de 1 arête à 0.60. Le BFS choisissait le second ; le Dijkstra moteur (Phase 3) choisit le premier.

**Reformulation** : trouver le chemin de produit de confiances maximal ≡ minimiser la somme de `-log(confidence)` — c'est un problème de plus court chemin pondéré, résolu par Dijkstra en O((V + E) log V).

```
poids(arête) = -log(confidence)   # transforme max-produit en min-somme
Dijkstra sur poids → chemin de confiance maximale
```

**Extension** — BFS bidirectionnel pour les chemins longs : partir simultanément de A et de B, terminer quand les deux fronts se rencontrent. Pour un graphe de diamètre D et facteur de branchement b, le BFS standard explore O(b^D) nœuds ; le BFS bidirectionnel explore O(b^(D/2)) — gain exponentiel sur les longues chaînes causales.

**Coût d'implémentation** : moyen.  
**Impact** : qualité des réponses CHAIN, abductif, et chemin de preuve dans `validate()`.

---

**Optimisation 4 — Cache LRU avec invalidation ciblée** *(production)*

Les mêmes requêtes reviennent sur les mêmes nœuds hubs. Un cache naïf vidé à chaque insertion est inutile sur un graphe vivant. La stratégie correcte est l'invalidation par nœud touché.

```
query_cache:        dict[(keyword, relation, domain), result]
node_to_cache_keys: dict[node_id, set[cache_key]]
```

Quand une arête (src, dst) est insérée, seules les entrées du cache référençant src ou dst sont invalidées. Toutes les autres entrées restent valides. Les requêtes répétées sur des nœuds stables sont servies en O(1).

**Coût d'implémentation** : moyen.  
**Impact** : décisif pour un agent en boucle continue où les mêmes concepts sont interrogés fréquemment.

### 7.3 Ce que l'on ne fait pas maintenant

Deux optimisations sont documentées ici mais **explicitement reportées** après les quatre fondations :

**Index sémantique (fastText + FAISS)** : projeter les labels de nœuds dans un espace vectoriel pour la recherche floue (synonymes, variantes morphologiques). Seuil de déclenchement : graphe > 500 000 arêtes par domaine, ou taux de requêtes sans résultat > 20 %.

**Graphe hiérarchique (coarse-to-fine)** : maintenir un graphe résumé en parallèle du graphe détaillé. Pertinent pour les requêtes cross-domaine sur des graphes de plusieurs millions d'arêtes.

### 7.4 Ordre d'implémentation et impact attendu

```
Optimisation              Coût    Impact            Prérequis
──────────────────────────────────────────────────────────────
1. Partitionnement domaine  Faible  Multiplicatif     Aucun
2. Index inversé labels     Faible  O(n)→O(k) requêtes  §1
3. Dijkstra conf. max       Moyen   Qualité raisonnement §2
4. Cache LRU ciblé          Moyen   Production stable    §2
──────────────────────────────────────────────────────────────
Reporté : index sémantique  Élevé   >500k arêtes/domaine §1-4
Reporté : graphe hiérarchique Élevé >1M arêtes cross-dom §1-4
```

Les quatre optimisations fondamentales sont suffisantes pour tenir 500 000 arêtes par domaine avec des temps de réponse inférieurs à 50 ms.

---

## 8. Communication et protocoles

### 8.1 Le problème actuel

Le moteur n'expose qu'une interface CLI. Pour intégrer GCN dans un système multi-agents ou un pipeline LLM, il faut construire un pont manuel (subprocess + parsing de sortie texte). C'est fragile, non scalable, et incompatible avec un paradigme agentique.

### 8.2 Interface de service

L'agent Evidra doit être exposé comme un **service**, pas comme un CLI. Concrètement, une API HTTP légère (FastAPI autour de `GCNEngine` + `CausalGraph`) avec les endpoints suivants :

| Endpoint | Description |
|---|---|
| `POST /analyze` | Texte → CIR JSON |
| `POST /ingest` | CIR JSON → intégration dans le graphe (avec provenance) |
| `GET /query/causes/{concept}` | Causes d'un concept, sourcées |
| `GET /query/effects/{concept}` | Effets d'un concept, sourcées |
| `GET /query/chain/{from}/{to}` | Chaîne causale entre deux concepts |
| `POST /validate` | Claim → CONFIRMED / UNCONFIRMED / CONTRADICTED |
| `GET /status` | État du graphe (densité, staleness, conflits ouverts) |
| `POST /directive` | Soumettre ou mettre à jour les directives de l'agent |
| `GET /alerts` | Alertes actives déclenchées par le moniteur |

**Sécurité `POST /directive` (2026-10-11).** La directive contenant les autorisations, sa mise à jour = escalade de privilèges potentielle : toute directive est signée (clé owner), chaque version entre au WAL (`directive:{version, auteur, motif}`), rollback vers la version précédente testé, rate-limit. Non signée = refusée. Regex `alert_on_*` validées au chargement (rejet des catastrophiques, timeout d'évaluation — anti-ReDoS).

### 8.3 Format de sortie adaptatif

Le même raisonnement doit produire des sorties différentes selon le destinataire :

- **LLM** : JSON structuré avec faits, sources, confiances — compact, sans prose. Le LLM lit, il ne reformule pas.
- **Humain** : texte verbalisé (`ReferenceDecoder`), citations en fin de paragraphe, niveau de confiance en prose.
- **Autre agent** : CIR complet avec provenance — protocole machine à machine.
- **Système d'alerte** : payload structuré avec niveau de sévérité, condition déclenchante, et graphe partiel concerné.

### 8.4 Protocole inter-agents

Dans un système multi-agents, le CIR est le **protocole de communication**. Un agent producteur extrait un CIR depuis une source et le transmet. Un agent consommateur l'intègre dans son graphe. La règle de traçabilité s'applique à chaque transfert : la provenance suit le CIR.

Un CIR transmis entre agents doit porter :
- L'identifiant de l'agent producteur
- Son niveau d'autorité dans le système (qui peut écrire quoi dans le graphe)
- La provenance complète de chaque arête

### 8.5 Sécurité inter-agents et anti-poisoning

**Le problème** : dans un système multi-agents, un agent malveillant ou compromis peut injecter des CIRs forgés pour polluer la mémoire de connaissance d'autres agents (graph poisoning). C'est particulièrement critique dans les domaines CTI où la manipulation de la connaissance causale peut induire de fausses alertes ou masquer de vraies menaces.

**Trois mécanismes de protection** :

**Authentification des agents producteurs**
Chaque CIR transmis est signé par l'agent producteur (signature HMAC ou asymétrique selon le niveau de confiance requis). L'agent consommateur vérifie la signature avant toute ingestion. Un CIR non signé ou à signature invalide est rejeté sans être inspecté.

**Niveaux d'autorité d'écriture**
La directive définit quels agents pairs sont autorisés à écrire dans quels domaines :

```json
"trusted_agents": [
  { "agent_id": "gcn-agent-osint-001", "domains": ["cybersecurity_cti"],
    "max_confidence_accepted": 0.80 },
  { "agent_id": "gcn-agent-legal-001", "domains": ["conformite_rgpd"],
    "max_confidence_accepted": 1.0 }
]
```

Un agent CTI ne peut pas écrire dans le domaine conformité. La confiance acceptée d'un agent pair est plafonnée — même un agent `trusted` ne peut pas injecter des relations à conf 0.99 si la directive dit max 0.80.

**Quarantaine des CIRs entrants**
Tout CIR reçu d'un agent pair est d'abord mis en statut NOUVELLE avec un flag `ingest_channel: "agent_push"`. Il ne passe en ACTIVE qu'après confirmation par au moins une **source indépendante non-agent** (adaptateur http_feed, local_files, ou autre adaptateur non `agent_push`) ou après validation manuelle si le domaine est critique.

**Définition d'indépendance** : deux sources sont indépendantes si elles utilisent des adaptateurs de types différents. Deux agents du même opérateur utilisant tous deux `agent_push` ne sont pas indépendants — ils partagent un vecteur de compromission commun.

**Lignage 2026-10-11** : l'adaptateur extrait `cite:[refs amont]` quand le document cite ses sources ; deux sources relayant le même amont (ou se citant mutuellement) = 1 confirmation indépendante, pas 2 — les confirmations circulaires ne sortent jamais une arête de quarantaine.

**Anti-Sybil** : une attaque Sybil consiste à faire confirmer une relation poisonnée par N agents complices se confirmant mutuellement. La contre-mesure est structurelle : la sortie de quarantaine exige obligatoirement au moins une confirmation depuis un adaptateur non-agent. Aucun nombre de confirmations `agent_push` ne peut sortir une arête de quarantaine sans cette confirmation externe.

**Rotation des clés** : les clés de signature des agents sont liées à leur identifiant dans la directive. Une clé compromise est révoquée en supprimant ou modifiant l'entrée `trusted_agents` — toutes les arêtes provenant de cet agent depuis la date de compromission supposée sont reclassées EN RÉVISION automatiquement.

### 8.6 Périmètre offline (décidé 2026-10-11 — option a : noyau offline, périphérie déclassée)

Contrainte fondatrice du moteur = tout local, pas de GPU, offline possible. Le SA la reprend : **WAL, registres, moteur, boucle, adaptateur `local_files` = 100 % offline, sans dégradation**. Chaque adaptateur/consommateur réseau (flux RSS, API, LLM, `agent_push`) déclare `requires_network: true` dans son manifeste ; son indisponibilité = statut `degraded` avec motif explicite au rapport de démarrage (§22) et en `GET /status`, jamais un crash ni un blocage du cycle. Le dogfood `code` tourne donc en offline total ; les phases réseau sont une périphérie optionnelle, pas une dépendance du noyau. Détection : sonde `requires_network` au démarrage + en `GET /status` (`degraded:{composant, motif}`) ; test d'acceptation : dogfood `code` 100 % offline (réseau coupé, zéro appel sortant, suite verte).

---

## 9. Directives et objectifs

### 9.1 Pourquoi les directives sont indispensables

Sans directive, un agent n'est pas un agent — c'est un système qui réagit sans but. La directive est ce qui transforme un moteur de raisonnement en acteur orienté. Elle définit ce que l'agent surveille, ce qu'il accepte, ce qu'il rejette, quand il agit.

### 9.2 Principe fondamental : la couche externe n'est pas hardcodée

La couche externe — tout ce qui arrive de l'extérieur du système — n'est jamais définie dans le code. Elle est entièrement décrite par la directive. Le SA ne "sait" pas à la compilation qu'il y a des flux RSS, des APIs, des fichiers ou des agents pairs. Il sait seulement comment recevoir des données via un adaptateur générique et comment interpréter ce qu'une directive lui demande de surveiller.

Concrètement : un adaptateur de source est un composant interchangeable qui transforme n'importe quel input externe en texte brut (ou CIR déjà formé) à destination du SA. La directive référence l'adaptateur et sa configuration — elle ne hardcode pas le type de source dans la logique agentique.

Ce principe garantit que le SA est **agnostique des sources**. Ajouter un nouveau type de source ne modifie pas la logique agentique — cela ajoute un adaptateur et une entrée de directive.

### 9.3 Structure d'une directive

Une directive est une spécification structurée (JSON) qui définit :

```json
{
  "agent_id": "gcn-agent-cti-001",
  "domain": "cybersecurity_cti",

  "sources": [
    {
      "adapter": "http_feed",
      "config": { "url": "https://nvd.nist.gov/feeds/json/cve/", "interval_seconds": 3600 }
    },
    {
      "adapter": "local_files",
      "config": { "path": "/data/reports/", "glob": "*.txt", "watch": true }
    },
    {
      "adapter": "agent_push",
      "config": { "endpoint": "/ingest", "trusted_agents": ["gcn-agent-osint-001"] }
    }
  ],

  "quality": {
    "min_confidence": 0.70,
    "min_extraction_method": "symbolic_rust",
    "min_confirmation_count": 1
  },
  "staleness": {
    "stale_after_days": 30,
    "invalidate_after_days": 90
  },
  "monitoring": {
    "watch_cycles": true,
    "watch_gaps_in_chains": ["exploitation_chain", "persistence_chain"],
    "alert_on_new_relation_involving": ["CVE-2024-.*", "ransomware"]
  },
  "actions": {
    "allowed": ["alert", "validate", "report", "ingest"],
    "forbidden": ["modify_existing_relation", "delete_node"]
  },
  "output": {
    "default_format": "json",
    "alert_endpoint": "https://siem.internal/api/gcn-alerts",
    "report_schedule": "daily"
  }
}
```

Le champ `adapter` désigne un composant interchangeable enregistré dans le SA — pas un type hardcodé. Ajouter un nouveau type de source revient à écrire un adaptateur et à le référencer dans une directive.

### 9.4 Ce que les directives contrôlent

**Périmètre** : le domaine et les sources définissent ce que l'agent surveille. Tout ce qui est hors périmètre est ignoré, même si c'est causalement intéressant.

**Qualité d'admission** : les seuils de qualité définissent ce qui entre dans le graphe. Un CIR silver non re-confirmé en dessous de 0.70 de confiance ne passe pas.

**Temporalité** : les paramètres de staleness définissent le rythme de vieillissement de la connaissance dans ce domaine. En CTI, une CVE non confirmée pendant 30 jours devient stale. En droit constitutionnel, une jurisprudence non re-confirmée pendant 5 ans reste valide.

**Actions autorisées** : l'agent ne peut faire que ce qui est dans la liste `allowed`. Un agent en mode lecture seule ne peut pas écrire dans le graphe. Un agent de validation ne peut qu'alerter et valider, pas ingérer.

---

## 10. Analyse des écarts (Gap Analysis — SA)

### 10.1 Tableau de synthèse

Tableau restreint aux capacités du périmètre SA. Toutes les capacités ci-dessous sont à implémenter dans le projet SA séparé — aucune n'entre dans gcn-core ou gcn-python.

| Capacité | État actuel | Ce qui manque |
|---|---|---|
| Persistance incrémentale | ❌ Absent | WAL (`graph_delta.jsonl`), index inversé (§7) |
| Partitionnement par domaine + sous-domaines | ❌ Absent | Graphes distincts, descriptif/normatif = sous-domaines (§7.2 opt.1) |
| Index inversé sur labels | ❌ Absent | O(n)→O(k), index tokens, relation, conf (§7.2 opt.2) |
| Dijkstra confiance max | ✅ Moteur / ❌ SA-exposition | Moteur Phase 3 (`pearl.rs:chain_topk`) ; reste SA : coquille `query_chain`, BFS bidirectionnel à trancher (§7.2 opt.3) |
| Cache LRU ciblé | ❌ Absent | Invalidation par nœud, O(1) requêtes répétées (§7.2 opt.4) |
| Registre de sources | ❌ Absent | reliability_score calculé, trusted/monitored/suspect/blocked (§6.3) |
| Formule d'arbitrage des conflits | ❌ Absent | score composite normalisé, règle quorum (§6.9) |
| Frontière CIR-noyau / arête enrichie SA | ❌ Absent | État mutable hors CIR, deux objets distincts (§6.8) |
| Cycle de vie de la connaissance | ❌ Absent | Décroissance T_domaine, statuts NOUVELLE→INVALIDÉE (§6.6) |
| Registre d'outils + politique de sélection | ❌ Absent | 6 niveaux priorité, anti-famine, séquentiel (§1.3) |
| Registre d'adaptateurs | ❌ Absent | Sources non hardcodées, extensibles par directive |
| Boucle de raisonnement | ❌ Absent | Sélection d'outils selon situation, non hardcodée |
| API de service | ❌ Absent | HTTP API, format adaptatif (§8.2) |
| Sécurité inter-agents | ❌ Absent | Signature, autorité, quarantaine, anti-Sybil (§8.5) |
| Protocole inter-agents | ❌ Absent | CIR avec provenance normalisée (§8.4) |
| Directives / objectifs | ❌ Absent | Spécification structurée de mission (§9) |
| Moniteur / alertes | ❌ Absent | Surveillance continue, conditions |
| Déduplication lexicale minimale | ❌ Absent | Table d'alias par domaine — P1 |
| Déduplication sémantique complète | ❌ Absent | Résolution d'entités embeddings — P3 |
| SLOs et benchmark agentique | ❌ Absent | Définis en §12.4 |

### 10.2 Ce qui est le plus urgent

Un blocant qui rend tout le reste inopérant dans un contexte agentique :

**L'absence de boucle agentique** : sans elle, aucune des capacités avancées ne peut s'exprimer. L'agent ne peut pas surveiller, agir, ni apprendre. La boucle est la première chose à implémenter dans le SA, même dans sa forme la plus simple — un cycle vide avec politique de sélection d'outils à zéro outil, qui s'étoffe progressivement.

**Tranché §21** : WAL d'abord, boucle no-op ensuite — §10.2 décrit l'urgence fonctionnelle, §21 l'ordre d'implémentation.

---

## 11. Architecture cible

### 11.1 Vue d'ensemble

La frontière entre le moteur (noyau) et le SA est matérialisée par le CIR. Le moteur produit et consomme des CIRs. Le SA orchestre, persiste, surveille et communique.

```
╔═════════════════════════════════════════════════════════════════════╗
║                    COUCHE EXTERNE (non hardcodée)                  ║
║  Tout ce qui vient de l'extérieur — types définis par directive,   ║
║  jamais en dur : flux, APIs, fichiers, agents, interfaces humaines  ║
╚══════════════════════════════╤══════════════════════════════════════╝
                               │
                               ▼
╔═════════════════════════════════════════════════════════════════════╗
║                    SYSTÈME AGENTIQUE (SA)                          ║
║                                                                     ║
║   ┌─────────────────────────────────────────────────────────────┐  ║
║   │              BOUCLE DE RAISONNEMENT                         │  ║
║   │  Observer → Sélectionner outils → Exécuter → Mémoriser     │  ║
║   │  (non hardcodée — pilotée par directives + situation)       │  ║
║   └──────────────────────┬──────────────────────────────────────┘  ║
║                          │ invoque                                  ║
║                          ▼                                          ║
║   ┌─────────────────────────────────────────────────────────────┐  ║
║   │                   REGISTRE D'OUTILS                         │  ║
║   │  fetch()  extract()  ingest()  query_*()  validate()        │  ║
║   │  alert()  report()   counterfactual()  query_gaps()  …      │  ║
║   │                                                             │  ║
║   │   extract() / raisonnement  →  ┌──────────────────────┐    │  ║
║   │                                │   MOTEUR (NOYAU)     │    │  ║
║   │                                │  gcn-core + gcn-py   │    │  ║
║   │                                │  dépendance externe  │    │  ║
║   │                                └──────────────────────┘    │  ║
║   └────────────────────────────┬────────────────────────────────┘  ║
║                                │ lit / écrit                        ║
║                                ▼                                    ║
║   ┌─────────────────────────────────────────────────────────────┐  ║
║   │              MÉMOIRE DE CONNAISSANCE                        │  ║
║   │                   (= intelligence)                          │  ║
║   │                                                             │  ║
║   │  Graphes causaux par domaine (WAL + index inversé)          │  ║
║   │  Provenance complète par arête                              │  ║
║   │  Cycle de vie : NOUVELLE→ACTIVE→CONFIRMÉE→STALE→INVALIDÉE  │  ║
║   │                                                             │  ║
║   │  Registre de sources                                        │  ║
║   │    confirmation_rate | contradiction_rate | reliability      │  ║
║   │    statut : trusted / monitored / suspect / blocked         │  ║
║   │    calculé depuis l'expérience — jamais déclaré à la main   │  ║
║   │                                                             │  ║
║   │  Ne se réinitialise jamais — accumule entre les cycles      │  ║
║   └─────────────────────────────────────────────────────────────┘  ║
║                                                                     ║
║   ┌─────────────────────────────────────────────────────────────┐  ║
║   │               REGISTRE D'ADAPTATEURS                       │  ║
║   │  Couche externe (non hardcodée) — définie par directive     │  ║
║   │  http_feed | local_files | agent_push | … (extensible)     │  ║
║   └─────────────────────────────────────────────────────────────┘  ║
║                                                                     ║
║   ┌─────────────────────────────────────────────────────────────┐  ║
║   │                    DIRECTIVES                               │  ║
║   │  Domaine | Sources | Qualité | Staleness | Actions | Sortie │  ║
║   └─────────────────────────────────────────────────────────────┘  ║
╚═════════════════════════════════════════════════════════════════════╝
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
    LLMs / RAG         Humains          Autres agents
    (JSON)             (texte verbalisé) (CIR + provenance)
```

**Lecture** : la boucle de raisonnement n'est pas hardcodée — elle sélectionne des outils selon la situation. Le moteur est l'un de ces outils (dépendance externe). La mémoire de connaissance est le pivot central que tous les outils partagent. Les adaptateurs sont le seul point de contact avec la couche externe, et leur liste n'est pas fixée dans le code.

### 11.2 La boucle de raisonnement (non hardcodée)

L'agent ne suit pas une séquence fixe câblée dans le code. À chaque cycle, il évalue la situation courante et sélectionne les outils appropriés parmi ceux disponibles.

```
┌─────────────────────────────────────────────────────────────────┐
│                     CYCLE DE RAISONNEMENT                       │
│                                                                 │
│  1. Observer la situation                                       │
│     - Nouvelles données disponibles via adaptateurs ?           │
│     - Requête entrante (validate, query) ?                      │
│     - Condition de monitoring déclenchée ?                      │
│     - Relations STALE dans la mémoire de connaissance ?         │
│                                                                 │
│  2. Sélectionner les outils pertinents                          │
│     selon la situation + les directives                         │
│                                                                 │
│     Nouvelles données    → fetch() → extract() → ingest()       │
│     Claim entrant        → validate()                           │
│     Question causale     → query_causes() / query_chain()       │
│     Cycle détecté        → alert()                              │
│     Gap dans chaîne      → query_gaps() → fetch() si priorité   │
│     Relations STALE      → décroissance, révision               │
│     Rien de notable      → aucun outil invoqué ce cycle         │
│                                                                 │
│  3. Exécuter les outils sélectionnés                            │
│     Chaque outil opère sur ou vers la mémoire de connaissance   │
│                                                                 │
│  4. Mettre à jour la mémoire de connaissance                    │
│     WAL append — jamais de snapshot complet                     │
│                                                                 │
│  5. Retourner au cycle suivant (délai défini dans la directive) │
└─────────────────────────────────────────────────────────────────┘
```

**La mémoire de connaissance** est le pivot de chaque cycle. Tous les outils lisent depuis elle ou écrivent vers elle. Elle persiste entre les cycles, entre les redémarrages, entre les tâches. Elle n'est jamais réinitialisée.

**Les outils sont les seuls points de contact** avec l'extérieur (adaptateurs, moteur, consommateurs). L'agent n'accède à rien directement — tout passe par un outil dont l'interface est définie et testable.

---

## 12. Priorités de développement

### 12.1 Critère de priorité

Les éléments sont classés par impact sur la viabilité agentique, pas par facilité d'implémentation. Tout le développement SA se fait dans le projet séparé — aucune de ces priorités ne touche gcn-core ou gcn-python.

### 12.2 P1 — Fondations indispensables (sans elles, rien ne fonctionne)

**P1.1 — Persistance incrémentale (WAL)**
Remplacer la réécriture complète de `graph.json` par un WAL (`graph_delta.jsonl`) et un index inversé sur les labels. Sans ceci, le SA ne peut pas tenir un flux continu — chaque insertion déclenche une réécriture complète du graphe.

**P1.2 — API HTTP minimale**
Exposer `analyze`, `ingest`, `validate`, `query/causes`, `query/effects` via FastAPI. C'est la couche de communication autour du moteur. Sans elle, le SA ne peut pas être consommé par des LLMs, d'autres agents, ni des interfaces humaines autres que le CLI.

**P1.3 — Déduplication lexicale minimale**
Implémenter une table d'alias par domaine (normalisations simples : casse, sigles, variantes connues), stockée dans la directive SA et appliquée par le SA avant ingestion. Sans elle, l'index inversé et Dijkstra opèrent sur un graphe fragmenté où `"auth"`, `"login"` et `"authentification"` sont trois nœuds distincts. Ne nécessite pas d'embeddings — une table définie dans la directive suffit pour les cas les plus fréquents. **Propriété** : la table d'alias est gérée par le SA (directive) ; le moteur fournit l'opérateur d'extraction mais n'a pas de vue sur les alias de domaine. **Surcouche réversible (2026-10-11)** : le `label_brut` est toujours conservé ; l'alias est une surcouche `{label_brut → canonique, règle, version}` — dé-fusion = suppression de surcouche, jamais de perte ; homonymes inter-contextes = nœuds distincts (pas de fusion cross-domaine sans arbitrage humain).

### 12.3 P2 — Intelligence agentique de base

**P2.1 — Cycle de vie de la connaissance**
Implémenter les statuts (NOUVELLE, ACTIVE, CONFIRMÉE, STALE, INVALIDÉE), la décroissance temporelle, et la résolution de conflits par arbitrage multi-sources. Géré par le SA autour du graphe persistant.

**P2.2 — Boucle agentique**
Implémenter la boucle PERCEVOIR → ÉVALUER → RAISONNER → PLANIFIER → AGIR → METTRE À JOUR, pilotée par un système de directives. Le SA invoque le moteur à l'étape PERCEVOIR (extraction) et RAISONNER (Pearl).

**P2.3 — Directives structurées**
Implémenter le format de directive (domaine, sources, qualité, staleness, monitoring, actions autorisées). Sans directive, la boucle agentique n'a pas d'objectif.

**P2.4 — Moniteur et alertes**
Implémenter la surveillance continue des conditions définies dans les directives : CYCLES, GAPS ciblés, relations STALE critiques, conflits non résolus.

### 12.4 P3 — Capacités avancées SA

**P3.1 — Déduplication sémantique complète**
Résolution d'entités complète (embeddings + clustering) — remplace la déduplication lexicale minimale de P1. Deux nœuds sémantiquement équivalents ("authentification", "auth", "login") sont fusionnés ou liés par un alias sémantique calculé, pas déclaré.

### 12.5 Métriques de succès SA

**Les seuils ci-dessous sont des cibles de conception — aucun n'est mesuré au 2026-09-25, le SA n'existant pas encore.** Les méthodes de mesure sont indiquées à titre indicatif pour guider l'implémentation future.

**Phase P1 — Fondations**

| Métrique | Seuil | Méthode de mesure |
|---|---|---|
| Latence `validate()` p99 | < 200 ms sur graphe 50k arêtes | Benchmark sur corpus CTI synthétique |
| Latence `query_causes()` p99 | < 50 ms sur graphe 100k arêtes | Idem |
| Taux CONFIRMED correct sur claims vrais | ≥ 0.85 | Évaluation sur 200 claims annotés manuellement |
| Taux faux UNCONFIRMED (claim vrai absent du graphe) | ≤ 0.10 | Idem (mesure de couverture) |
| Intégrité WAL après crash simulé | 0 perte de relation | Test d'injection de faute |
| Dimensionnement (2026-10-11) | RSS / temps rejeu / pause compaction mesurés à 50k arêtes | Mesure pendant la tranche §21(0), chiffres écrits avant P3 |

**Phase P2 — Boucle agentique**

| Métrique | Seuil | Méthode |
|---|---|---|
| Temps de cycle à vide (no-op) | < 10 ms | Profiling boucle |
| Taux d'alertes correctes sur corpus étiqueté | ≥ 0.80 précision, ≥ 0.75 rappel | Corpus d'événements CTI avec ground truth |
| Stabilité mémoire sur 72h de flux continu | Pas de fuite mémoire, croissance WAL linéaire | Test de charge |

**Benchmark agentique MVP (à définir avant P3)**

Un benchmark dédié doit être construit avant d'entrer en P3. Il doit couvrir :
- Un corpus de 1000 documents CTI avec ground truth causal
- 200 claims avec verdicts de référence (CONFIRMED / UNCONFIRMED / CONTRADICTED)
- 50 chaînes causales avec le chemin de référence connu
- Un scénario de flux continu sur 24h avec injection d'anomalies

---

## Conclusion

Le SA est un projet entier à construire depuis zéro. Il ne naît pas d'une extension du moteur — il naît d'un projet Python indépendant qui importe le moteur comme bibliothèque et construit autour de lui l'intelligence opérationnelle qui lui manque.

Le moteur fait trois choses avec précision : extraire des CIRs, raisonner causalement, valider la structure. Il s'arrête là. Tout le reste — persister, surveiller, décider, communiquer, vieillir la connaissance, arbitrer les conflits — appartient au SA.

Deux propriétés sont non négociables dans cette architecture :

1. **L'agent utilise des outils — il n'est pas hardcodé.** Sa logique de décision n'est pas une séquence fixe câblée dans le code. C'est ce qui le rend adaptable, testable, et extensible sans refactoring.

2. **L'agent a une mémoire de connaissance — pas une session.** La connaissance causale accumulée persiste et évolue. Elle n'est jamais réinitialisée. C'est ce qui lui permet de raisonner sur la durée, pas seulement sur une fenêtre de temps.

La séparation moteur / SA est la garantie que le noyau reste stable pendant que la couche d'intelligence évolue.

---

*Document produit le 2026-09-25. Architecture fondée sur l'inspection du code source GCN. Le SA n'est pas encore implémenté — ce document est une spécification de conception.*

---

# AMENDEMENTS 2026-10-11 — vérification code en main

## 12bis. Terminologie normative : moteur, modèle, SA (décidé 2026-10-11)

Trois objets distincts, confusion interdite :
- **Moteur** (`gcn-core` + `gcn-python`) : bibliothèque qui extrait, raisonne, valide — **et produit les modèles** (entraînement S4, checkpoints `.npz`, calibration). Tout ce qui touche aux poids vit ici, jamais dans le SA.
- **Modèle** : artefact produit par le moteur (checkpoint entraîné, encodeur, reranker). Versionné (hash), chargé par chemin + hash, `weights_only` / sans pickle. Le SA le **consomme** via contrat versionné, ne le modifie jamais (pas de fine-tune en ligne, pas de bump sauvage — cf. discipline M1a).
- **SA (Evidra)** : harness + mémoire + boucle. Il appelle le moteur (lib) et utilise des modèles (artefacts) comme outils. Les chargements ~25 s / ~1 Go (ex. XLM-R) sont des coûts **modèle**, pas des coûts harness — ils se paient une fois par modèle, pas par compétence, et jamais deux fois pour le même hash (cache par hash dans le registre de modèles du SA).
- Corollaire §23 : « poids lourds en lazy » = modèles consommés par des compétences, chargés par hash au premier usage ; le **code** des compétences reste eager (kilo-octets, validé au démarrage).

Fondés sur : Persistance (`cli/session.py`, `verbalizer/instructions.py`, `pipeline/cgnp.py`, `param_epoch.py`), R1/R2 (`reasoning/`, gel v3), requêtes Rust (`query.rs`, `edge.rs`), provenance Python (`ir_emitter.py:356-363`, `cgnp.py:936-948`), packaging (4 `pyproject.toml`, `>=3.10`, zéro entry-point, zéro FastAPI), dataset (`REGLE_EQUILIBRE_DATASET.md` v3.0, gold 219, gold-3000 planifié, gel R8/R10). Convention : **constaté** = prouvé `file:line` ; **décidé** = norme ; **provisoire** = valeur en attente de calibration, à ne jamais figer en constante.

## 13. Harness modulaire plug-and-play (noyau < 500 lignes, 3 contrats)

**13.1 Contrats versionnés (`harness/1.0`, parallèle à `reason/1.0`).** `Tool` (`name, version, input/output_schema, cost_hint, side_effects, run(ctx, args) -> ToolResult`) ; `Adapter` (`poll(since) -> list[RawDoc]`, `ack()`) ; `Store` (`append, lookup, snapshot`). Découverte par entry-points `evidra_tools` / `evidra_adapters` (`importlib.metadata`, stdlib — constaté : aucun entry-point existant, départ de zéro sans antériorité). Le noyau ne référence aucun nom concret ; la directive mappe `nom → paramètres`. **Décidé** : toute PR SA important du moteur autre chose que `analyze/analyze_batch/reason/reason_question/verify_path/CausalGraph` est rejetée (pendant de la garde `grep gcn_transformers` du socle).
**13.2 Coquilles moteur minces, logique nulle.** `extract→analyze_batch` (dédupe par lots prouvée `engine.py:428-449`), `reason_chain→reason()` (pure, bornée budget=16/profondeur≤2/top-k=5, `derived` jamais ingérés — `reasoning/engine.py:1-11,161-167`), `validate→reason()+verify_path` (O(L·E)). Jamais de métier dans la coquille.
**13.3 Permissions appliquées par le harness.** Matrice `allowed/forbidden`, verbes `read/ingest/modify/delete/alert/egress`, défaut tout-interdit-sauf-`read` ; chaque appel passe `can(tool, verb, scope)` ; `delete` exige motif WAL (calque des gates P1-rigidité : `respond_validated`, Export `--force`, `revoke` restreint `dialogue.py:457-471`, suppressions tracées `_dels`).
**13.4 Tâches persistées.** File JSONL (`id, type, budget, deadline, état`), consommée par P4–P6, expirée = `ABANDONED` tracé avec motif ; replay tolérant par ligne (recopie du pattern `session.py:275-400`, prouvé par l'audit lifecycle).
**13.5 Ressources budgétées.** Par cycle dans la directive : `max_tool_calls, max_ingest_per_cycle, max_cycle_ms, max_wal_bytes`. Ordres de grandeur initiaux **mesurés** (commit `2b2453c` : find 12ms, merge 8ms, reason 9ms, BFS 2.5ms aux caps 500n/2000e). Dépassement = `budget:` tracé + report (vocabulaire R1 réutilisé). **Appels lourds 2026-10-11** : `analyze_batch` et chargements de modèles tournent en worker avec timeout issu de la directive ; dépassement = `degrade` + report, jamais de blocage des alertes P1 ni des requêtes API (`max_cycle_ms` ne peut pas interrompre un appel en cours — le timeout est dans le worker, pas dans le scheduler). **Débit** : docs/sec mesuré par la tranche verticale §21(0) sur CPU sans GPU — les budgets par cycle sont fondés sur ce chiffre, pas sur les 4 timings op.
**13.6 Test de non-régression architecturale.** Si une fonctionnalité exige de modifier le noyau plutôt qu'ajouter un plugin, c'est le design du plugin qui est mauvais.

## 14. Mémoire : WAL SA distinct (ne pas réutiliser SessionStore)

**Constaté** : `SessionStore` = photo atomique tmp+replace **sans fsync** + `graph_delta.jsonl` append **sans fsync ni lock**, écrit **au `save()` seulement** (perte entre mutation et save), **sans LSN/seq/checksum**, rotation photo-puis-unlink non atomique (doublons admis `session.py:299-300`), suppressions non rejouables (forcent photo via `_dels`), `history.jsonl` disque jamais compacté, dédup replay incluant volatiles (même fait rejoué = doublon logique), `param_epoch` + cache `analyze` 100 % volatils (`cgnp.py:1199-1233`, 1024 FIFO).
**Décidé** : WAL SA séparé — fsync par batch, seq par ligne, tombstones rejouables, snapshot versionné + backup `.prev`, compaction sur taille octets, clé de dédup **sans** champs volatiles, tag de cache incluant `param_epoch.current()` (O(1), `cgnp.py:1064-1065). Tolérance par ligne recopiée (skip+compteurs, jamais d'abort). Partitionnement par domaine dès le jour 1 (layout, pas refactor futur). **Sémantique 2026-10-11** : `ack()` après fsync du batch (au-moins-une-fois + dédup idempotente §16.4) ; kill -9 mi-batch → replay sans perte ni doublon logique (test exigé). **File morte** : 3 échecs d'extraction sur le même doc = quarantaine + log, fin du rejeu infini (calque 3-échecs §23). **Migration** : `version` dans snapshot + enveloppes + manifeste (§22) ; `load()` refuse ou convertit toute version inconnue (fail-closed, calque R4 convert-or-retrain) — jamais de corruption silencieuse.

## 15. Caches, contexte, recherche

**Caches** : requêtes SA à invalidation par nœud (`node_to_cache_keys`, §7 opt.4) ; cache moteur interne, jamais lu directement (bumps via `update()`, staleness prouvée+fixée `20163da`).
**Contexte** : fenêtre bornée par profil (`max_context_edges, max_tool_results`), dégradation par score §6.9, `truncated: n` écrit (calque discipline P3/P4 : `question[:500]`, journal replié jamais droppé à 200 tours `dialogue.py:354-408`, `nlu_fallback_counts` exposés). `reason()` ne prenant que `(kw_from, kw_to, graph, budget)`, le moteur ne voit jamais le contexte SA — faisable par construction.
**Recherche** : index inversé P1 ; Dijkstra `-log(conf)` pour `query_chain` via coquille mince sur le moteur Phase 3 (max-produit ≡ min-somme ; le BFS ne subsiste qu'en résiduel/temporel) ; sémantique **interdite** avant seuils — déclencheur principal 2026-10-11 : taux d'UNCONFIRMED sur requêtes lexicales > seuil (à calibrer §16.2), garde `semantic_index_min_edges: 500000` ou >20 % requêtes vides en repli, en garde de directive.

## 16. Connaissance, pertinence, mises à jour (avec calibration fondée)

**16.1 Enveloppe SA** (§6.8 inchangé, correct) + règle anti-boucle : une arête `derived` ne confirme jamais ses prémisses (le moteur ne l'interdit pas — test SA explicite exigé).
**16.2 Corpus de calibration dérivé du gold, pas ad hoc.** Gold 219 phrases → ~200 paires claim→verdict gratuites (phrase gold = CONFIRMED attendu ; paires croisées sans lien = UNCONFIRMED synthétiques tracés). Les 200 claims manuels §12.5 réservés à la **validation** (split calibration/validation, jamais les mêmes données). Balayage quorum ∈ {1.5,2,2.5,3} × Nmax ∈ {20,50,100}, métrique précision/rappel ≥0.80/0.75. Discipline du gel R8/R10 : N<30/classe → gel (`GATES.md:34`, démo `grid_f1_thresholds.py` exit 2). En attendant : valeurs étude `provisoire`, arbitrage `EN RÉVISION` si ratio < 3.0. **Arbitrage comparé 2026-10-11** : noisy-OR vs produit §6.9, comparatif chiffré sur ce corpus avant de figer — la formule actuelle n'a pas de justification probabiliste. **Premier rapporteur** : en CTI le premier juste est « contredit » par la meute — un arrivant isolé contre consensus passe `EN RÉVISION` (bonus `novelty` borné ou gel, jamais pénalité de fiabilité) au lieu d'être écrasé par le quorum.
**16.3 `reliability(source)` figée provisoire** : `0.7·confirmation_rate + 0.3·(1−contradiction_rate)`, plancher `n_min=5` (en dessous : 0.5 neutre + `monitored` forcé — même logique que N_min=20 dataset, adaptée à l'échelle source). Ne double-compte pas l'extraction : le `reliability_score = mean × provenance_ratio` moteur (`query.rs:2135-2172`, testé `integration_backend.rs:1041-1099`) reste la composante **arête**. **Non démontré** : l'interaction multiplicative score-arête × reliability-source n'est pas prouvée sans double-pondération — garde : interdiction de multiplier sans normalisation + test dédié (corpus §16.2) avant mise en production.
**16.4 Clé de dédup sans volatiles** (corrige la limite prouvée du replay session). WAL append-only : historique des états rejouable.

## 17. Sécurité : canaux, signatures, sorties modèle

**17.1 Plafond de confiance par canal** (ferme l'angle mort §8.5 : un flux HTTP compromis injectait du 0.99 sans friction). Quarantaine `agent_push` inchangée (sortie sur confirmation non-agent — anti-Sybil structurellement correct).
**17.2 Signature selon topologie** : mono-opérateur (cas actuel, owner solo) → **HMAC-SHA256**, clé **par agent** (jamais partagée — compromission indétectable sinon), rotation = remplacement + `EN RÉVISION` depuis date supposée ; multi-opérateurs → **Ed25519**, clés publiques dans `trusted_agents`. Enveloppe `signature: {algo, key_id}` ; refus fail-closed si non signé ou algo non listé (discipline `load()` fail-fast `instructions.py:415-471`). **Anti-rejeu 2026-10-11** : enveloppe étendue `{algo, key_id, nonce, ts}`, fenêtre d'acceptation 5 min, nonce vu = rejet. **Clés** : stockage documenté (fichier 0600 + variable d'environnement, jamais dans le repo ni les logs).
**17.3 Modèle-sur-graphe = outil sous contrat.** Précédent prouvé : `gcn-transformers` isolé par garde CI + contrat `CausalEncoder` testé + M1a (`20163da`). Contrat versionné + tests de contrat obligatoires par plugin (`score_candidates, propose_alias`) ; aucun accès mémoire direct ; `extraction_method` déclarée (ex. `ml_sa_alias`).
**17.4 Transcription stricte.** Modèle→SA : schéma validé, rejet + log, jamais de défaut silencieux ; contrôle de portée (hors domaine = rejeté) ; marquage `derived` + justifications obligatoires ; quarantaine selon canal. Sous-seuil = compté + journalisé (calque P4-rigidité `dialogue.py:579-580,620-624`). SA→modèle : manifest de ce que le modèle a vu (nœuds/arêtes/tag — traçabilité).
**17.5 Protocole pickle CodeBERT** (sandbox réseau isolée, jamais dev) : (1) télécharger révision pinnée (`revision` câblée `load_hf_model`) ; (2) `pickletools.dis()` stdlib sans exécuter — allowlist `torch.*/OrderedDict/numpy`, rejet si `os/subprocess/eval` (pendant du gate `guarded_np_load`) ; (3) convertir `torch.load` → **safetensors**, prod n'accepte plus que lui + `weights_only=True` en garde permanente.

**17.6 Rétention et effacement (2026-10-11).** Le WAL append-only contredit le droit à l'effacement : politique par domaine (`retention_jours`, purge des preuves après délai, registre des suppressions versionné) ; la tombstone marque, la purge efface — les deux sont tracées. Sans politique écrite, retirer `conformite_rgpd` des exemples de domaines. Test : purge d'un doc → preuve illisible + suppression enregistrée.

## 18. Provenance Python : règle d'enveloppement (prouvée, pas supposée)

**Constaté** : `emit()` construit toujours une provenance mais `cgnp.forward` ne passe jamais `doc_ref` → `ref=None`, `span` = un token marqueur ou `"synthetic"` (`ir_emitter.py:356-363` via `cgnp.py:936-948`) ; `add_cir` **n'écrit jamais** la provenance (`instructions.py:160-243`, lecture seule en `1084-1120`) ; `discourse.py:130-136` idem (`ref=None`). Seuls écrivains CIR Python : `ir_emitter.py:356`, `discourse.py:130`.
**Décidé** : le SA enveloppe chaque CIR Python en injectant `ref` (doc connu de l'adaptateur) + `span` réel (offsets de l'adaptateur) par-dessus le span marqueur. Aucune modification moteur requise (exception licite §1.5 non déclenchée — le Rust porte déjà `Provenance{ref?, span!, method!, version!, at!}` `edge.rs:104-112`, `check_missing_provenance` en warning `validate.rs:128-130`). **Hash contenu 2026-10-11** : l'enveloppe porte aussi `content_sha256` du texte source ; revérification = re-hash + comparaison, échec = `ref_invérifiable` → quarantaine (§28.3) — une URL qui change ou un fichier édité ne laisse plus une preuve morte.

## 19. Auto-apprentissage restreint (3 compteurs, le reste = accumulation)

Registre de sources calculé (formule §16.3, jamais déclaré) ; alias candidats (co-confirmation N fois) à **promotion humaine obligatoire** ; rapport d'écart seuils-vs-confirmations, jamais d'auto-modification. Fondement : sans corpus annoté, auto-modifier des seuils = dérive non mesurée (leçon 2026-10-02 : pas de statistique sur des miettes). S4/poids gelé sans dataset gelé.
**Garde anti-circularité et taille minimale (2026-10-11, incident table 11→19).** Constaté : minage sur 0,5 % du corpus avec ses propres listes de marqueurs, puis validation de ces mêmes marqueurs — verdicts fermes (GARDER/REJETER/gel) sans fondement. Règles : (1) aucun verdict de règle sous ~30 arbitrages/classe sur minage large (FR+EN minimum sur corpus multilingue, jamais une langue seule) ; (2) interdiction de valider avec les marqueurs ayant servi au minage (double liste indépendante ou hold-out de marqueurs) ; (3) un gel exige un **négatif avéré** (minage large négatif), jamais une absence sur échantillon ; (4) tout verdict reste `provisoire` daté et révisable. Vaut pour le moteur (calibration §16.2) comme pour le SA (confirmations, §16.1 anti-boucle).

## 20. Démarrage froid + résiduel

**Bootstrap** : ingestion initiale tracée + registre seedé `monitored` par directive (jamais `trusted` déclaré — §6.3) ; tout UNCONFIRMED au jour 0 est normal et écrit. **Reste non tranchable ici** : HMAC-vs-Ed25519 au-delà de la règle §17.2 (re gears au 2ᵉ opérateur), pickle (exige réseau, §17.5), valeurs finales quorum/Nmax/poids (exigent corpus §16.2).

## 21. Ordre d'implémentation tranché (§10.2 vs §12.2)

WAL (§14) avant boucle : une boucle sans persistance n'apprend rien, et le WAL est le socle testable (replay, compaction, tombstones). Séquence : (0) **tranche verticale gold-219** (2026-10-11) : `local_files` sur les 219 phrases → `analyze_batch` → enveloppement `ref/span` → seuils → `ingest` → `validate` sur paires croisées — sortie = 5 nombres (précision/rappel CONFIRMED, taux UNCONFIRMED, latence médiane/p99, docs/sec), même mauvais : sans eux tout dimensionnement est inventé ; (1) scaffolding hors workspace + dépendance path editable (dev synchrone, version pinnée à la première release) ; (2) WAL + index + enveloppe §16.1 + enveloppement provenance §18, domaine `code` dogfood (`local_files` sur ce repo, zéro réseau) ; (3) boucle no-op + politique 6 niveaux + 1 adaptateur ; (4) API (FastAPI, dépendance côté SA assumée — constaté : absente du moteur, à déclarer côté SA) ; (5) calibration §16.2 dès gold suffisant.

## 22. Démarrage : séquence moteur constatée + modèle SA

**Constaté** (`run_discuss`, `discuss.py:158-258` ; CLI Rust stateless `main.rs:216-225`) : (1) `SessionStore` vide ; (2) `load()` : photo → replay journal (tolérant, `skipped`) → **resnapshot immédiat** → vecs mmap → historique (`session.py:275-400`) ; (3) `from_pretrained` (1 bump, cache vide, `EPOCH` reparti de 0 : premier `analyze` = miss) ; (4) `handler.graph = session.graph` sauf `--graph` qui écrase (incohérence connue : journal ancien gardé) ; (5) reseeds d/q-blocs ; (6) `from_history` : `turn=max`, 3 derniers topics, `lang_thread`, 200 derniers tours (`dialogue.py:432-442`). **Perdu à chaque restart** : `pending` (clarification en cours), `last_candidates`, `lang_override`, entrées `analyze/query/summary`, config (défauts recréés), `_NLU_FALLBACKS` (zéro), `checkpoint_hash` (ni lu ni comparé au manifest), index vecs stale silencieux.
**Décidé — démarrage SA en 5 phases, chacune avec rapport écrit** (même type que `load()->{...}`) : (1) **Manifeste** (`sa_manifest.json` : versions harness/directive, hash moteur attendu, seq WAL) — divergence = mode déclassé explicite, jamais poursuite silencieuse ; (2) **WAL** : snapshot + replay seq/checksum + tombstones (pas de resnapshot systématique qui masque les corruptions) ; (3) **Registre** : sources + alias + file de tâches (`ABANDONED` repris, deadlines réévaluées) ; (4) **Modèles+moteur** (§12bis) : `from_pretrained` (moteur-lib) + chargement des modèles-outils par hash (registre SA, dédupliqué : même hash = un seul chargement) + check `param_epoch` + préchauffage cache optionnel (1 phrase sentinelle) ; (5) **Boucle** : reprise au `pending` **persisté** (la clarification survit — contrairement au `pending: None` actuel), troncation par pertinence avec `truncated: n`.

## 23. Compétences : constat, modèle, chargement tranché

**Constaté : aucun mécanisme dynamique.** Requêtes = `enum` fermée + `match` exhaustif (`query.rs:433-526,2174-2274`, ajout = 6 edits) ; CLI = `clap` + `match` (`main.rs:43-150,225-447`) ; Python = `COMMANDS: set` + cascade `if` (`instructions.py:26-52,690-742`) ; encodeurs = `Protocol` + injection constructeur (seul pattern sain, sans découverte, `from_pretrained` en dur `engine.py:181-241`). Grep : zéro `entry_points/@register/factory` ; seuls TODOs explicites non implémentés (`CHANGELOG.md:167-169`).
**Décidé — compétence = paquet installable** : manifeste obligatoire (`name, version semver, harness_requis, permissions, canaux, cost_hint`, schémas I/O) — sans lui, refus fail-closed ; cycle de vie `discovered → validated → enabled → running → disabled/quarantined` (3 échecs de contrat = `quarantined` auto) ; isolation (copies en entrée comme le hit `analyze` = deepcopy, seule `ingest()` écrit via harness, sous-graphe du domaine + budget) ; catégories `extract/reason/maintain/serve` (lecture : `reason, CYCLES, GAPS, PROVENANCE, RELIABILITY` — tous prouvés ; jamais d'écriture directe) ; contrat `harness/1.0` (exigence supérieure = `disabled` motivé).
**Décidé — chargement froid P1, tiède P2, chaud jamais avant P3.** Froid : discovery + validation + chargement au démarrage, rapport écrit. Tiède : directive relue à chaque cycle → on/off sans restart (code inerte si `disabled`) — 90 % du bénéfice, 0 % du risque. Chaud interdit avant : WAL verrouillé + quiescence + rollback (le WAL actuel n'a ni lock ni fsync — `session.py:220` — le chaud y serait une corruption prouvée, pas un risque théorique ; et le restart est dominé par le chargement XLM-R ~25 s, incompressible des deux façons). Règle : mise à jour de *code* = restart ; mise à jour de *comportement* = directive. Le vrai chaud n'a de sens qu'en multi-opérateurs sans fenêtre de maintenance.

## 24. Conversation : trajet prouvé, 3 niveaux, enveloppes unifiées

**Constaté** (`discuss.py:158-411`, `dialogue.py:476-647`) : l'utilisateur ne parle jamais au modèle ML — il parle à une boucle qui traduit : `str` → `handle()` (DSL `parse_command`, sinon `nlu_route` + `semantic_resolve` cosine > 0.3, sinon `format_response` heuristique) → `engine.analyze()` (question aussi ingérée best-effort, poids 0.5 `dialogue.py:567-581`) → graphe (`find_causes/effects/path`) → `QueryVerbalizer`/gabarits → `str`. **Trois niveaux stricts** : tenseurs `np.ndarray` (modèle↔couches, jamais exposés — `cgnp.py:459-948`) ; CIR `dict` (échange : pipeline→graphe→`reason()`, `engine.py:332-339`) ; texte (humain). Le réseau **produit** des CIR, ne les **lit** jamais pour raisonner (`reason()` symbolique pur, non branché sur `forward`). `respond()`/`UserResponse` (`respond.rs:26-45`, total, jamais d'`Err`, `{status, phrase, lang, result?, caveats, suggestions}`) existe mais **n'est pas branché** sur `discuss`.
**Décidé** : le SA unifie sur deux enveloppes — `ToolResult{status, payload, warnings, cost}` côté machine (calque de `UserResponse` : `caveats/suggestions` → `warnings/cost`), texte verbalisé côté humain ; `respond()` branché comme sortie Rust (fin de l'exception `discuss`), modèle-outil = sous-graphe + manifest en entrée, `ToolResult` en sortie, routé vers mémoire (`ingest`), utilisateur (verbalisation) ou autre outil.

## 25. Auto-interrogation : état, tâches, cycle (manque, pas choix)

**Constaté** : aucune commande d'état (`/status` inexistant, aucune requête globale dans l'enum ~23, `cache_stats()` — `cgnp.py:1164` — jamais appelé hors tests) ; le `status` de `info` = statut du tour (`ok/unanswered/clarified`), pas du système ; les tâches n'existent pas (rien à désigner).
**Décidé — principe : tout ce que le SA sait sur lui-même est interrogeable** (les compteurs existent déjà tous : hits, skips, fallbacks, dropped — seul le verbe manque) : (1) `GET /status` (§8.2, à brancher) : `{edges, nodes, domains, wal_seq, cache, epoch, uptime, degraded?}` — lecture pure, zéro mécanisme neuf ; (2) tâche X : `id + état + budget consommé/restant + deadline + motif` (exige la file §13.4 — d'où sa persistance) ; (3) cycle courant : `{phase, outil en cours, budget restant}` (trivial en P1 un-outil-par-tick, échantillonné ensuite).

## 26. Reçus d'exécution + sous-agents (décidé 2026-10-11)

**26.1 Reçu obligatoire (jamais de fire-and-forget).** Calque de `(response, info)` (`dialogue.py:476`) et de `UserResponse` total (`respond.rs:312-330`) : `ToolResult = {status: ok|degrade|refused|failed, payload, warnings, cost{ms, appels}, trace_ref (seq WAL)}`. `refused` (gate `can()`) = décision, pas erreur. Le scheduler n'enchaîne jamais sans lire le reçu précédent (fonde le séquentiel §1.3). Audit « qu'a fait le SA ? » = lecture WAL. Sans mutation, pas d'écriture WAL : un cycle no-op = zéro écriture (le reçu vit en mémoire, seul son coût alimente les compteurs).
**26.2 Sous-agent = outil borné, pas enfant libre.** Compétence `delegate(spec)` : but + sous-graphe + **sous-enveloppe budgétaire** (jamais d'extension) ; sortie = `ToolResult` unique ; écritures via `ingest()` parent, marquées `ingest_channel: "subagent"` + id parent (même quarantaine que `agent_push` §8.5) ; **profondeur max 1** (écrit en directive, non négociable) ; séquentiel sauf N slots autorisés sur partitions disjointes. Reçu +`subagent_id, budget_alloué/consommé` ; 3 `failed` → `delegate` quarantined (faute localisable).
**26.3 Interdits P1-P2, ouverts P3 (recommandation adoptée).** Pourquoi : gate `can()` non prouvé (un `delegate` mal contraint contourne les permissions par héritage), budgets sans unité éprouvée (rafales imprévisibles = nombres inventés, discipline anti-constantes), besoin nul en dogfood `code`, et chaque confiance inter-mécanismes est un M1a potentiel (précédent `20163da`). P1-P2 : `delegate` au registre `disabled`, spec figée (contrat, sous-budget, profondeur 1, quarantaine) — comme `semantic_index_min_edges`, garde écrite avant besoin. **Gate d'ouverture P3** (mesurable) : `can()` testé adversarialement (discipline `14d1167`) + budgets calibrés sur ≥100 cycles + quarantaine prouvée en dogfood. Jamais : profondeur > 1, parallèle sur partitions non disjointes, héritage par élargissement (sous-ensemble strict des droits parent, dans `can()`).

## 27. Schéma complet + flux (référence visuelle, 2026-10-11)

Rappel §12bis : MOTEUR (lib, produit les modèles) → MODÈLE (artefact hashé, consommé) → SA (harness, appelle et utilise).

```
COUCHE EXTERNE (directive, jamais en dur) : flux RSS · fichiers · APIs · agents · LLM · humains
    │ poll        │ push         │ pull        │ requêtes      │ questions
    ▼             ▼              ▼             ▼               ▼
HARNESS EVIDRA (noyau < 500 lignes)
┌───────────┐ ┌────────────┐ ┌───────────┐ ┌──────────────────────┐
│ADAPTATEURS│ │ REGISTRE   │ │ SCHEDULER │ │ GATE can(tool,verb)  │
│(plugins)  │ │COMPÉTENCES │ │6 priorités│ │ défaut: read seul    │
│http_feed  │ │discovered→ │ │séquentiel │ │ delete ⇒ motif WAL   │
│local_files│ │validated→  │ │+ budgets  │ │ refusé = loggé       │
│agent_push │ │enabled→    │ │anti-famine│ └──────────┬───────────┘
│…          │ │running     │ └─────┬─────┘            │ directive
└─────┬─────┘ │(quarantined└──▶│   │              relue/cycle ◀────┘
      │       └─────┬──────┘   ▼   ▼         (tiède : on/off sans restart)
      │             │   ┌──────────┐ ┌────────────┐ ┌──────────────────┐
      │             │   │MOTEUR lib│ │MODÈLES hash│ │MANIFESTES harness│
      │             │   │analyze/  │ │dédupliqués │ │/1.0 : Tool/      │
      │             │   │reason/   │ │lazy, jamais│ │Adapter/Store,    │
      │             │   │CYCLES/.. │ │modifiés    │ │validés au démarr.│
      │             │   └──────────┘ └────────────┘ │(froid)           │
      │             │        │            │         └──────────────────┘
      └─────────────┴────────┴────────────┴──────────────┬──────────────
                                                        ▼
MÉMOIRE (= intelligence) : WAL seq+fsync+tombstones → snapshot+backup
  index inversé │ enveloppes {cir_noyau, status, compteurs, fiabilité}
  /domaine/ (cti·code·droit) │ registre sources │ registre modèles
  file de tâches │ table alias
       │                        │                           │
       ▼                        ▼                           ▼
  LLM (JSON)              Humains (verbalisé +          Agents (CIR+prov
  compact, sans prose     citations + confiance)        +signature)
```

Flux : F1 ingestion (`poll → extract → analyze_batch → enveloppement ref/span → seuils → ingest → WAL`, rejet = `dropped` compté) ; F2 cycle (situation → 6 priorités → `can()` → exécution → contexte borné `truncated: n` → WAL si mutation, zéro écriture si no-op) ; F3 requête (index O(k) → `reason()` pure ou Dijkstra `-log(conf)` → preuves + `min(premises)` → `ToolResult`) ; F4 validation (`CONFIRMED` / `UNCONFIRMED` jamais FAUX / `CONTRADICTED`, sources citées) ; F5 maintenance (`STALE` → re-confirmation / arbitrage → `EN RÉVISION` → verdict / tombstone) ; F6 modèle-outil (sous-graphe + manifest → `score/propose` → 4 temps → `ingest` avec méthode déclarée, jamais d'accès direct) ; F7 conversation (`str → handle → ingest` poids 0.5 → graphe → verbalisation → `str`, `respond()` branché) ; F8 auto-interrogation (`/status`, tâche X, cycle courant — §25).
Démarrage (§22) : manifeste → WAL → registres → modèles(hash)+moteur → pending persisté → boucle, rapport par phase.
Compétences (§23) : paquet → manifeste → schémas → code eager (poids lazy par hash) → on/off directive ; code = restart, comportement = directive, chaud interdit avant P3.
Invariants : (1) rien n'écrit sauf `ingest()`/maintenance ; (2) rien ne sort sans provenance ; (3) le moteur reçoit des requêtes ponctuelles, jamais contexte/enveloppe ; (4) le SA n'entraîne rien (accumule/adapte à 3 compteurs/révise par directive versionnée).

## 28. Sécurité du contenu ingéré : injection indirecte (2026-10-11)

**Constaté** : le flux F1 transforme tout `RawDoc` non fiable (RSS, fichier, `agent_push`) en claims → requêtes → verbalisations, potentiellement lues par un LLM consommateur (§8.3). La quarantaine `agent_push` (§8.5) filtre le **canal**, pas le **contenu** : un document peut porter des instructions en langage naturel (« ignore tes seuils »), des `ref_doc`/offsets forgés, une fausse provenance, ou une contradiction fabriquée d'une source fiable. Aucune section ne couvrait ce vecteur — c'est le trou n°1 d'un système dont les sorties citent des sources.
**Décidé — 28.1 Menaces (fermé).** Taxonomie : `instruction` (impératif adressé au système dans le texte) ; `provenance_forgée` (`ref_doc` invérifiable) ; `contradiction_fabriquée` (contredit une source fiable sans preuve) ; `saturation` (volume pour noyer — renvoi budgets §13.4). Chaque menace = motif de quarantaine nommé et loggé.
**Décidé — 28.2 Le contenu ingéré n'est jamais une instruction.** Le texte source est donnée citée, jamais ordre : `extract` sépare `texte_cité` (stocké, cité) de tout champ interprété ; aucun prompt/affichage ne concatène du texte source en position d'instruction (verbaliseurs : citations quotées et attribuées, jamais fusionnées au gabarit — renvoi §24, niveau texte).
**Décidé — 28.3 Provenance vérifiée, pas crue.** `ref_doc` résolvable au moment de l'ingestion (sinon `ref_invérifiable` → quarantaine ou confiance au plancher du canal) ; offsets re-vérifiés contre le document ; contradiction avec source fiable → arbitrage F5 avec fardeau de preuve sur l'arrivant (renvoi §18).
**Décidé — 28.4 Quarantaine contenu (distincte de la quarantaine canal).** Claim suspect stocké (traçabilité) mais `quarantined_content` : exclu des requêtes et des `CONFIRMED`, visible en audit ; sortie par arbitrage humain ou corroboration indépendante (2e source, canal différent — même définition d'indépendance que §8.5).
**Décidé — 28.5 Tests d'acceptation.** Corpus adversarial minimal figé : document « oublie tes instructions » → `instruction` ; faux `ref_doc` → `provenance_forgée` ; contradiction d'un claim gold sans preuve → `contradiction_fabriquée` ; verdicts attendus écrits ; à jouer contre chaque nouvel adaptateur (discipline audit moteur `14d1167`). Statut des seuils : `ARBITRAIRE + protocole` — la grille de décision (quarantaine immédiate vs plafond de confiance) sera calibrée sur ce corpus, pas fixée ici.

## 29. Bloquants côté moteur (2026-10-11 — plan dataset et benchmarks à venir)

**B1 — Confiances non calibrées (Ph5 NO-GO, `GATES.md`).** ECE 0.33-0.55 (>> 0.15), monotonie non, N=81 < 100 → 6b, quantification enterrée. Conséquence SA : traiter toute `conf` moteur comme non calibrée (plafonds par canal §17.1, `provisoire` §16.2, `EN RÉVISION` par défaut §16.2) jusqu'à re-calibration sur gold suffisant.
**B2 — Checkpoint non re-mesuré (`CHANGELOG Lot A Baselines`).** `val_edge_f1` contradictoire (0.468 vs 0.1867, harnais distincts) — aucun checkpoint consommé par le SA tant que non re-mesuré sur harnais unique ; registre modèles par hash (§12bis) vide en attendant.
**B3 — Dataset à venir (`plan-dataset-3M.md`, `plan-annotation-cir.md`, `ROADMAP.md`).** Cible 3M de phrases, stock ~146k uniques (5 %), gap ~2 854k ; 50-95j à 3 machines ; gold actuel 219 phrases, 8 relations à 0 occurrence, gel R8/R10 acté (`GATES.md:34`). Conséquence SA : calibration §16.2 (balayage quorum × Nmax) et levée des gels impossibles avant gold-3000 — phases §21 (1)-(3) n'en dépendent pas.
**B4 — Benchmarks à construire (§12.5).** Benchmark agentique MVP (1000 docs, 200 claims, 50 chaînes, 24h de flux) + SLOs P1/P2 inexistants au 2026-09-25. Gate d'entrée P3 : benchmarks construits et verts, pas une date.
**Décidé — ordre §21 inchangé.** B1-B4 ne bloquent ni scaffolding, ni WAL, ni boucle, ni API : ils gatent uniquement la calibration (5) et l'ouverture P3 (`delegate`, sémantique). Tout nombre dépendant de B3/B4 reste `provisoire` (§12bis).

## 30. Corrections tranche 2 (2026-10-11 — audit externe)

Tranche verticale gold-219 en §21(0) (5 nombres avant tout dimensionnement) ; `published_at` + `content_sha256` (§6.9, §18) ; alias réversibles + `label_brut` (P1.3) ; worker+timeout + débit docs/sec (§13.5) ; ack-après-fsync + file morte + migration fail-closed (§14) ; directive signée + audit + rollback + anti-ReDoS (§8.2) ; nonce/ts + stockage clés (§17.2) ; rétention/effacement (§17.6) ; lignage anti-confirmations-circulaires (§8.5) ; arbitrage comparé + premier-rapporteur (§16.2) ; CONTRADICTED opérationnalisé (table fermée, §5) ; Pearl borné aux assertions sourcées (§2) ; sémantique sur taux UNCONFIRMED (§15) ; no-op = zéro écriture (§26.1, §27). P3 : export métriques, cross-domaine fédéré, comparaison RAG/GraphRAG, console de revue humaine.
Nom **Evidra** (2026-10-11, remplace Hermès : marque notoire + collision Meta Hermes engine + saturation GitHub agents/IA ; package `evidra` libre PyPI vérifié, `cairn`/`griot` écartés après vérification registres).
