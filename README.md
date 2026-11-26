# Fil rouge — « Les événements font-ils bouger la Métropole ? »

Projet de groupe — Données & pipelines SQL (M1IADATA), Mastère 1 Expert en IA.
Énoncé et grille : [`enonce/`](enonce/).

**Groupe** : _à compléter_ · **Membres** : _à compléter_
**Restitution** : vendredi 27/11/2026 · **Rendu final** : vendredi 04/12/2026, 23h59 (à confirmer)
**Dataset publié** : _lien HuggingFace + tag de version à compléter_

## Objectif

Pour chaque occurrence d'événement de l'agenda OpenAgenda de la Métropole Rouen Normandie, calculer un
**indice de surfréquentation** = passages vélo observés près du lieu pendant l'événement ÷ passages habituels
sur le même créneau (méthode détaillée dans [`sql/fr_03_indice.sql`](sql/fr_03_indice.sql)).

> Ce n'est **pas** un taux d'usage (part des participants venus à vélo) : ni la fréquentation des événements
> ni les validations de titres de transport ne sont en open data.

## Jeu de données utilisé

- [x] Sources réelles (API OpenAgenda + portail Métropole)
- [ ] Jeu réel photographié (`secours/reel/`, clé USB)
- [ ] Jeu synthétique du kit (`secours/synthetique/`) — **données fictives**

## Architecture

```
collecte/     collecteurs asynchrones : OpenAgenda (événements), Lovélo (GBFS, bonus)
chargement/   chargement idempotent des comptages vélo horaires (eco-counter-data) + profilage
transform/    nettoyage des événements (HTML, dédoublonnage, rapprochement des lieux)
etl/          orchestration, quarantaine, contrôles qualité bloquants, Dataset Card, publication Hub
sql/          schéma (fr_01), requêtes métier Q1-Q4 (fr_02), indice R1-R5 (fr_03)
tests/        tests fournis + tests du groupe
docs/         profilage des sources, optimisation EXPLAIN
secours/      API locale de secours + jeu synthétique
```

_Schéma du flux et choix d'outils au regard du volume réel : à compléter._

## Répartition du travail

Deux parties menées en parallèle. Le point de contact entre elles, ce sont les tables du schéma
[`sql/fr_01_schema.sql`](sql/fr_01_schema.sql).

### Partie A : comptages et SQL (Freshnel Houenou)

| Tâche | Fichiers | Critère de la grille |
|---|---|---|
| Chargement des comptages corrigé d'après la fiche d'anomalies : décodage de `location`, rejet des lignes `deleted`, dédoublonnage au lieu de la somme, `status` normalisé | `chargement/load_comptages.py` | 3. Chargement |
| Q1 (calendrier complet), Q2 (comparaison aux 4 semaines précédentes), Q4 (pannes) | `sql/fr_02_requetes_metier.sql` | 4. SQL avancé |
| Q3 : optimisation mesurée avec `EXPLAIN (ANALYZE, BUFFERS)` | `docs/optimisation.md` | 4. SQL avancé |
| R1 à R4 : `event_zone`, vue `v_indice_evenement`, top 10 avec `RANK()`, couverture | `sql/fr_03_indice.sql` | 5. Indicateur |

### Partie B : événements et pipeline ( Axel SOUDE)

| Tâche | Fichiers | Critère de la grille |
|---|---|---|
| Nettoyage des événements : tests fournis au vert, 3 tests ajoutés, chargement des tables `events`, `event_occurrences` et `venues` | `transform/clean_events.py`, `tests/` | 3. Nettoyage |
| Collecteur OpenAgenda : pagination par curseur, fenêtres en parallèle, retries, reprise | `collecte/openagenda_collector.py` | 2. Collecte |
| Pipeline ETL : logs, quarantaine, contrôles bloquants, `run_report.json`, Dataset Card, publication Hub | `etl/` | 6. Industrialisation |
| Lovélo (bonus) | `collecte/lovelo_collector.py` | Bonus |

### En commun

- Le profilage des sources (fait : [`docs/profilage.md`](docs/profilage.md)).
- Le README, les limites de l'indice et la Dataset Card.
- La préparation de la restitution.
- La relecture croisée de chaque pull request : chaque membre doit pouvoir expliquer tout le code.

**Dépendance** : R1 et R2 ont besoin des événements et des lieux en base. La partie B commence donc par le
nettoyage, sur le jeu synthétique, avant le collecteur.

### Calendrier

| Quand | Partie A | Partie B |
|---|---|---|
| Mar. 24 et mer. 25/11 | Chargement corrigé, Q1, Q2, Q3 | Nettoyage, tests, chargement des événements |
| Jeu. 26/11 | Q4, R1 à R4 | Collecteur OpenAgenda |
| **Ven. 27/11 : restitution** | Démo du top 10 et de la couverture | Démo du run, de la quarantaine et des tests |
| Jusqu'au 04/12 | Finitions SQL et optimisation | ETL complet, publication Hub, Lovélo |

### Règles git

- Une branche par tâche (par exemple `chargement-comptages`, `clean-events`), fusionnée dans `main` par pull request relue par l'autre membre.
- Chacun a son `.env` local, copié depuis `.env.example`, et ne le commite jamais.

## Installation

```bash
cp .env.example .env                 # puis renseigner OA_KEY et HF_TOKEN (jamais committés)
docker compose up -d                 # PostgreSQL 17, base « metropole »
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
psql -h localhost -U etl -d metropole -f sql/fr_01_schema.sql
```

> Si le conteneur du kit (`m1iadata-pg`) tourne déjà sur le port 5432, ne lancez pas celui-ci :
> créez simplement la base dans le conteneur existant (`CREATE DATABASE metropole`).

## Commandes

```bash
# Profilage des sources (chiffres de docs/profilage.md), puis chargement des comptages vélo
python chargement/profilage.py
python chargement/load_comptages.py                       # télécharge depuis le portail
# ou, sans retélécharger : --file data/brut/eco-counter-data.parquet (copie faite par le profilage)
# ou, en secours : --file secours/synthetique/eco-counter-data.csv
# lignes rejetées et raison : data/quarantaine/comptages_rejetes.csv

# Collecte des événements
python collecte/openagenda_collector.py

# Tests
pytest -q

# Requêtes SQL
psql -h localhost -U etl -d metropole -f sql/fr_02_requetes_metier.sql   # après le chargement des comptages
psql -h localhost -U etl -d metropole -f sql/q3_mesure.sql               # facultatif : mesures EXPLAIN de Q3
psql -h localhost -U etl -d metropole -f sql/fr_03_indice.sql
```

### Mode secours (API indisponible)

```bash
python secours/serveur_api_local.py               # terminal 1
export OA_API=http://localhost:8765/openagenda/v2  # terminal 2
export OA_KEY=secours
export PORTAIL_API=http://localhost:8765/ods/api/explore/v2.1/catalog/datasets
```

Détails : [`secours/README.md`](secours/README.md).

## Choix argumentés

_À compléter au fil des séances (outils, règles de nettoyage, optimisation retenue, seuils qualité…)._

**Chargement des comptages** (règles de [`docs/profilage.md`](docs/profilage.md)) :
- Deux lignes pour le même (compteur, heure) sont deux versions de la même mesure, pas deux sens de
  circulation : on en garde une (non supprimée, puis validée > corrigée > brute) au lieu de les additionner.
- `status` est conservé dans `counts_hourly.status` (`brut`, `corrige`, `valide`) pour pouvoir filtrer
  sur la donnée validée si besoin.
- Les coordonnées des compteurs sont décodées depuis `location` (point WKB) : le jeu réel n'a pas de colonnes lat/lon.

**Requêtes métier et optimisation** ([`docs/optimisation.md`](docs/optimisation.md)) :
- Calendrier complet par `generate_series` : une heure sans mesure reste NULL, jamais 0.
- Q2 par `LAG(passages, 168 × k)` sur ce calendrier sans trou : 168 lignes = 7 jours exactement.
- Optimisation retenue : vue matérialisée du calendrier, triée et indexée (Q2 : 2,6 s → 1,3 s, plus de tri
  sur disque). Elle est rafraîchie par `load_comptages.py` après chaque chargement.

## Limites de l'indice

_À compléter : ce que l'indice mesure et ne mesure pas, couverture (part des événements sans capteur)._

## Usage déclaré de l'IA

| Partie | Outil | Usage |
|---|---|---|
| Mise en place du dépôt (arborescence, README, config) | Claude Code | Génération du squelette à partir du kit |
| Profilage (`chargement/profilage.py`, `docs/profilage.md`) | Claude Code | Script de profilage, remplissage de la fiche à partir de sa sortie, règles relues par le groupe |
| Chargement des comptages (`chargement/load_comptages.py`, `tests/test_load_comptages.py`) | Claude Code | Corrections du chargement d'après la fiche d'anomalies et tests associés, relus et expliqués |
| _à compléter_ | | |

Chaque membre du groupe est en mesure d'expliquer l'ensemble du code.
