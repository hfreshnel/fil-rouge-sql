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

- [ ] Sources réelles (API OpenAgenda + portail Métropole)
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
# Profilage puis chargement des comptages vélo
python chargement/load_comptages.py --profile
python chargement/load_comptages.py                       # ou --file secours/synthetique/eco-counter-data.csv

# Collecte des événements
python collecte/openagenda_collector.py

# Tests
pytest -q

# Requêtes SQL
psql -h localhost -U etl -d metropole -f sql/fr_02_requetes_metier.sql
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

## Limites de l'indice

_À compléter : ce que l'indice mesure et ne mesure pas, couverture (part des événements sans capteur)._

## Usage déclaré de l'IA

| Partie | Outil | Usage |
|---|---|---|
| Mise en place du dépôt (arborescence, README, config) | Claude Code | Génération du squelette à partir du kit |
| _à compléter_ | | |

Chaque membre du groupe est en mesure d'expliquer l'ensemble du code.
