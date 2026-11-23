# Cas fil rouge — « Les événements font-ils bouger la Métropole ? »

**Module** : Données & pipelines SQL (M1IADATA) — Mastère 1 Expert en Intelligence Artificielle
**Format** : **rendu de groupe** (binômes ou trinômes). Les TP0 à TP5 sont, eux, en **rendu individuel**.
**Temps en séance** : 30 min à 1 h par jour de formation, puis travail en autonomie.
**Restitution** : vendredi 27/11/2026 · **Rendu final** : *date à confirmer* (proposé : vendredi 04/12/2026, 23h59)

## Contexte

La Métropole Rouen Normandie publie en open data son agenda d'événements et des données de mobilité
(comptages vélo, vélos en libre-service Lovélo, réseau de transport Astuce). Elle veut savoir si les
événements du territoire modifient les déplacements autour de leurs lieux. Vous construisez le pipeline
de données qui permet de répondre, et vous livrez un premier indicateur.

## Question et livrable

Pour chaque occurrence d'événement, calculer un **indice de surfréquentation** :
passages observés près du lieu pendant l'événement ÷ passages habituels sur le même créneau.

> Ce n'est **pas** un taux d'usage (part des participants venus à vélo) : la fréquentation des événements
> et les validations de titres de transport ne sont pas en open data. Cette limite doit figurer dans la Dataset Card.

Méthode imposée (détaillée dans `fil_rouge/sql/fr_03_indice.sql`) :
1. **Zone** : compteurs vélo à moins de 800 m du lieu, stations Lovélo à moins de 500 m.
2. **Fenêtre** : de 1 h avant le début à 1 h après la fin.
3. **Référence** : même créneau, même jour de semaine, 4 semaines précédentes, hors autres événements proches.
4. **Indice** = observé / référence ; NULL si aucun capteur ou référence nulle (jamais 0).

## Sources

| Source | Rôle | Obligatoire |
|---|---|---|
| Agenda OpenAgenda de la Métropole (API, clé gratuite) | Événements, lieux, dates | Oui |
| Comptages vélo horaires (`eco-counter-data`, portail Métropole) | Faits : passages par heure | Oui |
| Salles et équipements culturels, adresses (Base Adresse Nationale) | Référentiels des lieux | Oui |
| Lovélo (flux GBFS temps réel, à collecter) | Vélos disponibles par station | Bonus |
| Réseau Astuce (GTFS + GTFS-RT) | Ponctualité pendant les événements | Bonus |

## Étapes, au rythme des séances

| Séance | Travail fil rouge |
|---|---|
| 1 | Groupes, profilage des sources (`chargement/load_comptages.py --profile`), fiche d'anomalies |
| 2 | Schéma `fr_01_schema.sql`, chargement des comptages, requêtes Q1 et Q2 |
| 3 | Q3 : une optimisation documentée avec EXPLAIN (ANALYZE, BUFFERS) |
| 4 | Collecteur asynchrone OpenAgenda (`collecte/openagenda_collector.py`), Lovélo en option |
| 5 | Nettoyage des événements (`transform/clean_events.py`) : les tests de `tests/` doivent passer |
| 6 | Pipeline ETL complet (squelette du TP5), quarantaine, contrôles bloquants, publication sur le Hub |
| 7 | Restitution |

## Livrables (dépôt Git du groupe)

```
fil-rouge-<groupe>/
├── README.md                  # architecture, installation, commandes, choix argumentés, usage déclaré de l'IA
├── requirements.txt           # versions figées
├── collecte/                  # collecteur OpenAgenda (+ Lovélo)
├── transform/                 # nettoyage des événements
├── etl/                       # orchestration, quarantaine, contrôles qualité
├── sql/                       # schéma, requêtes Q1-Q4, indice R1-R4
├── tests/                     # au moins les tests fournis + 3 tests à vous
├── docs/profilage.md          # anomalies constatées par source et règle appliquée
├── docs/optimisation.md       # plan EXPLAIN avant / après + gain
└── run_report.json            # volumes, rejets par raison, durée du dernier run
```
\+ lien vers le dataset publié sur le Hub HuggingFace (tag de version, Dataset Card générée).

## Restitution (10 min + 5 min de questions)

1. Architecture et choix d'outils au regard du volume réel
2. Démo : run, logs, quarantaine, tests qui passent
3. Résultats : top 10 des événements par indice, couverture (part des événements sans capteur)
4. Limites : ce que l'indice mesure et ne mesure pas

## Règles

- Aucun jeton (OA_KEY, HF_TOKEN) dans le dépôt : `.env` + `.gitignore`.
- Usage d'assistants IA autorisé s'il est déclaré dans le README ; chaque membre doit pouvoir expliquer tout le code.
- **Si une API est indisponible** (OpenAgenda, portail, Lovélo) : basculez sur l'API locale de secours, sans changer votre code (voir `secours/README.md`). Lancez `python secours/serveur_api_local.py` puis définissez `OA_API`, `PORTAIL_API` (et `--gbfs-url` pour Lovélo). Le jeu réel photographié par l'intervenante est distribué sur clé USB ; à défaut, le jeu synthétique du kit a la même forme et les mêmes défauts. Indiquez dans le README et la Dataset Card quel jeu vous avez utilisé : la note ne dépend pas de la disponibilité d'une API.
