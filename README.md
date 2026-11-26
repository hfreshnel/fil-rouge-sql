# Fil rouge â€” Les Ã©vÃ©nements font-ils bouger la MÃ©tropole ?

Projet de groupe â€” DonnÃ©es & pipelines SQL
M1IADATA â€” MastÃ¨re 1 Expert en Intelligence Artificielle

Ã‰noncÃ© et grille d'Ã©valuation : [`enonce/`](enonce/).

**Groupe :** 2
**Membres :** Freshnel Houenou et Axel Soude
**Restitution :** vendredi 27/11/2026
**Rendu final :** vendredi 04/12/2026 Ã  23h59 (Ã  confirmer)

**Dataset publiÃ© :** [Axel229/fil-rouge-sql-metropole](https://huggingface.co/datasets/Axel229/fil-rouge-sql-metropole) â€” [Version v1.0](https://huggingface.co/datasets/Axel229/fil-rouge-sql-metropole/tree/v1.0).

---

## Objectif

Pour chaque occurrence d'Ã©vÃ©nement de l'agenda OpenAgenda de la MÃ©tropole Rouen Normandie, calculer un **indice de surfrÃ©quentation cyclable** :

**Indice = passages vÃ©lo observÃ©s prÃ¨s du lieu pendant l'Ã©vÃ©nement / passages habituels sur le mÃªme crÃ©neau.**

La mÃ©thode dÃ©taillÃ©e est disponible dans [`sql/fr_03_indice.sql`](sql/fr_03_indice.sql).

Cet indice ne reprÃ©sente pas un taux d'utilisation du vÃ©lo par les participants. Nous ne disposons ni des donnÃ©es de frÃ©quentation des Ã©vÃ©nements ni des validations de titres de transport permettant de mesurer directement les dÃ©placements des participants.

## Sources de donnÃ©es utilisÃ©es

- [x] API OpenAgenda : Ã©vÃ©nements, lieux et occurrences.
- [x] Portail Open Data de la MÃ©tropole Rouen Normandie : comptages horaires Eco-counter.
- [x] Base Adresse Nationale (BAN) : gÃ©olocalisation et rapprochement des lieux.
- [ ] DonnÃ©es LovÃ©lo GBFS : intÃ©gration facultative non rÃ©alisÃ©e dans cette version.
- [ ] Jeu rÃ©el de secours (`secours/reel/`).
- [ ] Jeu synthÃ©tique du kit (`secours/synthetique/`) â€” donnÃ©es fictives.

Les donnÃ©es de secours ne sont utilisÃ©es qu'en cas d'indisponibilitÃ© des sources en ligne. La collecte rÃ©elle OpenAgenda ayant fonctionnÃ©, les donnÃ©es synthÃ©tiques n'ont pas Ã©tÃ© utilisÃ©es pour constituer le dataset publiÃ©.

## Architecture du projet

```text
collecte/
    openagenda_collector.py
    lovelo_collector.py

chargement/
    profilage.py
    load_comptages.py

transform/
    clean_events.py

etl/
    quality.py
    run_pipeline.py
    publish_hub.py

sql/
    fr_01_schema.sql
    fr_02_requetes_metier.sql
    fr_03_indice.sql

tests/
    tests de nettoyage, collecte, qualitÃ© et pipeline

docs/
    profilage.md
    optimisation.md

data/
    donnÃ©es de rÃ©fÃ©rence et fichiers intermÃ©diaires

secours/
    API locale de secours et jeu synthÃ©tique
```

### Flux de traitement

Deux flux de donnÃ©es sont collectÃ©s et prÃ©parÃ©s sÃ©parÃ©ment avant leur exploitation dans PostgreSQL.

**Flux des Ã©vÃ©nements :**

API OpenAgenda â†’ collecteur asynchrone â†’ nettoyage et dÃ©doublonnage â†’ rapprochement des lieux avec la BAN â†’ PostgreSQL.

**Flux des comptages :**

Portail Open Data de la MÃ©tropole â†’ tÃ©lÃ©chargement Eco-counter â†’ profilage et nettoyage â†’ PostgreSQL.

**Analyse et publication :**

PostgreSQL â†’ requÃªtes SQL Q1 Ã  Q4 et R1 Ã  R4 â†’ calcul de l'indice et couverture â†’ export Parquet avec PyArrow â†’ publication sur Hugging Face.

Le pipeline ETL assure Ã©galement la journalisation, la quarantaine des Ã©vÃ©nements rejetÃ©s, les contrÃ´les qualitÃ© bloquants et la gÃ©nÃ©ration de `run_report.json`.

**Technologies utilisÃ©es :** Python, aiohttp, PostgreSQL, SQL, PyArrow, Parquet et Hugging Face Hub.

## RÃ©partition du travail

Les deux parties ont Ã©tÃ© menÃ©es en parallÃ¨le. Leur point de raccordement repose sur les tables du schÃ©ma [`sql/fr_01_schema.sql`](sql/fr_01_schema.sql).

### Partie A : comptages et SQL â€” Freshnel Houenou

| TÃ¢che | Fichiers | CritÃ¨re |
|---|---|---|
| Chargement et nettoyage des comptages : dÃ©codage de `location`, rejet des lignes supprimÃ©es, dÃ©doublonnage et normalisation de `status` | `chargement/load_comptages.py` | 3. Chargement |
| Q1 : calendrier complet des compteurs | `sql/fr_02_requetes_metier.sql` | 4. SQL avancÃ© |
| Q2 : comparaison avec les quatre semaines prÃ©cÃ©dentes | `sql/fr_02_requetes_metier.sql` | 4. SQL avancÃ© |
| Q3 : optimisation mesurÃ©e avec `EXPLAIN (ANALYZE, BUFFERS)` | `docs/optimisation.md` | 4. SQL avancÃ© |
| Q4 : dÃ©tection des pÃ©riodes de panne | `sql/fr_02_requetes_metier.sql` | 4. SQL avancÃ© |
| R1 Ã  R4 : rattachement des lieux, indice, Top 10 et couverture | `sql/fr_03_indice.sql` | 5. Indicateur |

### Partie B : Ã©vÃ©nements et pipeline â€” Axel Soude

| TÃ¢che | Fichiers | CritÃ¨re |
|---|---|---|
| Collecte OpenAgenda : pagination par curseur, fenÃªtres mensuelles en parallÃ¨le, reprises et nouvelles tentatives | `collecte/openagenda_collector.py` | 2. Collecte |
| Nettoyage des Ã©vÃ©nements : normalisation, suppression des doublons, rapprochement des lieux et chargement PostgreSQL | `transform/clean_events.py`, `tests/` | 3. Nettoyage |
| Pipeline ETL : logs, quarantaine, contrÃ´les qualitÃ© et rapport d'exÃ©cution | `etl/run_pipeline.py`, `etl/quality.py` | 6. Industrialisation |
| Export des donnÃ©es en Parquet et publication Hugging Face | `etl/publish_hub.py` | 6. Industrialisation |

### Travail commun

- Profilage des sources et documentation dans [`docs/profilage.md`](docs/profilage.md).
- DÃ©finition des limites de l'indice.
- Documentation du projet et Dataset Card.
- Relecture croisÃ©e du code.
- PrÃ©paration et rÃ©alisation de la restitution.

**DÃ©pendance entre les parties :** R1 et R2 nÃ©cessitent les Ã©vÃ©nements et les lieux en base. La collecte et le nettoyage des Ã©vÃ©nements doivent donc Ãªtre rÃ©alisÃ©s avant le calcul de l'indice.

## Calendrier

| Date | Partie A | Partie B |
|---|---|---|
| 24 et 25/11 | Chargement corrigÃ©, Q1, Q2 et Q3 | Nettoyage, tests et chargement des Ã©vÃ©nements |
| 26/11 | Q4 et R1 Ã  R4 | Collecteur OpenAgenda et industrialisation ETL |
| 27/11 | DÃ©monstration du Top 10 et de la couverture | DÃ©monstration du pipeline, de la quarantaine et des tests |
| Jusqu'au 04/12 | Finalisation SQL et documentation | Finalisation ETL, export et publication Hub |

L'intÃ©gration LovÃ©lo, prÃ©vue comme bonus facultatif, n'a pas Ã©tÃ© retenue dans cette version.

## RÃ¨gles Git

- DÃ©velopper les fonctionnalitÃ©s sur des branches dÃ©diÃ©es.
- Fusionner les modifications aprÃ¨s relecture.
- Ne jamais committer le fichier `.env`.
- Chaque membre utilise son propre fichier `.env`, crÃ©Ã© Ã  partir de `.env.example`.
- Ne jamais publier de clÃ©s API ou de jetons d'authentification.

## Installation

CrÃ©er et activer un environnement virtuel :

```bash
python -m venv .venv
```

Sous Windows PowerShell :

```powershell
.venv\Scripts\Activate.ps1
```

Sous Linux ou macOS :

```bash
source .venv/bin/activate
```

Installer les dÃ©pendances :

```bash
pip install -r requirements.txt
```

CrÃ©er le fichier `.env` Ã  partir de `.env.example`, puis renseigner les variables nÃ©cessaires :

```env
OA_KEY=
HF_TOKEN=
PG_DSN=postgresql://etl:etl@localhost:5432/metropole
```

DÃ©marrer PostgreSQL avec Docker Compose si aucun conteneur PostgreSQL adaptÃ© n'est dÃ©jÃ  disponible :

```bash
docker compose up -d
```

**Attention :** `sql/fr_01_schema.sql` contient des instructions `DROP TABLE`. Il ne doit Ãªtre exÃ©cutÃ© que pour initialiser une base neuve, jamais sur une base contenant dÃ©jÃ  les donnÃ©es du projet.

## Commandes principales

### 1. Profilage et chargement des comptages

```bash
python chargement/profilage.py
python chargement/load_comptages.py
```

Le chargement tÃ©lÃ©charge les donnÃ©es Eco-counter depuis le portail Open Data et les insÃ¨re dans PostgreSQL.

Les lignes rejetÃ©es et leurs motifs sont enregistrÃ©s dans :

```text
data/quarantaine/comptages_rejetes.csv
```

### 2. Collecte OpenAgenda

Exemple de collecte de janvier 2024 Ã  novembre 2026 :

```bash
python -m collecte.openagenda_collector --start 2024-01 --end 2026-11 --out evenements_bruts.jsonl
```

Le collecteur utilise la pagination par curseur, des fenÃªtres mensuelles parallÃ¨les, des nouvelles tentatives en cas d'erreur et un mÃ©canisme de reprise.

### 3. ExÃ©cution du pipeline ETL

```bash
python -m etl.run_pipeline
```

Pour exÃ©cuter le pipeline sans chargement PostgreSQL :

```bash
python -m etl.run_pipeline --no-load
```

Le pipeline effectue le nettoyage, les contrÃ´les qualitÃ©, l'enregistrement de la quarantaine et la gÃ©nÃ©ration de `run_report.json`.

Les journaux sont disponibles dans :

```text
logs/etl.log
```

### 4. Tests

```bash
pytest -q
```

### 5. RequÃªtes SQL

Ã€ exÃ©cuter aprÃ¨s le chargement des donnÃ©es et l'initialisation du schÃ©ma :

```bash
psql -h localhost -U etl -d metropole -f sql/fr_02_requetes_metier.sql
psql -h localhost -U etl -d metropole -f sql/q3_mesure.sql
psql -h localhost -U etl -d metropole -f sql/fr_03_indice.sql
```

Le script `q3_mesure.sql` sert Ã  mesurer les performances de la requÃªte Q3.

### 6. Export et publication Hugging Face

Pour gÃ©nÃ©rer les fichiers Parquet sans les publier :

```bash
python -m etl.publish_hub
```

Pour actualiser les exports et publier le dataset :

```bash
python -m etl.publish_hub --publish
```

Le dÃ©pÃ´t publiÃ© est accessible Ã  l'adresse :

https://huggingface.co/datasets/Axel229/fil-rouge-sql-metropole

Version publiÃ©e : `v1.0`.

## Mode secours

En cas d'indisponibilitÃ© des sources en ligne, le projet dispose d'une API locale et de donnÃ©es de secours.

```bash
python secours/serveur_api_local.py
```

Les paramÃ¨tres de connexion Ã  l'API locale sont documentÃ©s dans [`secours/README.md`](secours/README.md).

Le jeu synthÃ©tique n'est pas utilisÃ© lorsque les sources rÃ©elles sont disponibles. Il ne doit pas Ãªtre mÃ©langÃ© au dataset rÃ©el publiÃ©.

## Choix argumentÃ©s

### Collecte des Ã©vÃ©nements

La collecte OpenAgenda est rÃ©alisÃ©e de maniÃ¨re asynchrone. Les donnÃ©es sont rÃ©cupÃ©rÃ©es par fenÃªtres mensuelles avec pagination par curseur, afin de gÃ©rer les volumes importants et de pouvoir reprendre une collecte interrompue.

Sur la pÃ©riode de janvier 2024 Ã  novembre 2026, la collecte a rÃ©cupÃ©rÃ© **6 919 Ã©vÃ©nements bruts**.

### Nettoyage et rapprochement des lieux

Le traitement des Ã©vÃ©nements comprend :

- La normalisation des titres, descriptions et mots-clÃ©s.
- Le nettoyage du HTML dans les descriptions.
- La suppression des doublons par identifiant OpenAgenda et par rapprochement mÃ©tier.
- Le contrÃ´le de cohÃ©rence des dates.
- Le rapprochement des lieux Ã  partir de leur identifiant OpenAgenda, puis par comparaison des noms et des villes.
- La validation gÃ©ographique des coordonnÃ©es dans le pÃ©rimÃ¨tre de la MÃ©tropole.

Les coordonnÃ©es BAN incertaines ne sont pas utilisÃ©es : les Ã©vÃ©nements concernÃ©s conservent des coordonnÃ©es manquantes plutÃ´t que d'introduire une gÃ©olocalisation erronÃ©e.

RÃ©sultat du nettoyage :

- 6 186 Ã©vÃ©nements conservÃ©s.
- 733 Ã©vÃ©nements rejetÃ©s, principalement des doublons.
- 4 avertissements de gÃ©olocalisation lors des contrÃ´les qualitÃ©.
- Taux de rejet : environ 10,59 %.

Les Ã©vÃ©nements rejetÃ©s sont conservÃ©s dans un fichier de quarantaine avec leur motif.

### Chargement des comptages

Les rÃ¨gles de chargement sont dÃ©taillÃ©es dans [`docs/profilage.md`](docs/profilage.md).

- Deux lignes correspondant au mÃªme compteur et Ã  la mÃªme heure sont traitÃ©es comme des versions d'une mÃªme mesure, et non comme deux passages Ã  additionner.
- Les lignes supprimÃ©es sont rejetÃ©es.
- Les versions sont dÃ©partagÃ©es selon leur statut : validÃ©e, corrigÃ©e, puis brute.
- Le statut est conservÃ© dans `counts_hourly.status`.
- Les coordonnÃ©es des compteurs sont dÃ©codÃ©es depuis le champ `location`.

Le chargement rÃ©el a permis d'intÃ©grer 35 compteurs et 1 059 766 mesures horaires.

### RequÃªtes mÃ©tier et optimisation

Les requÃªtes Q1 Ã  Q4 permettent de construire un calendrier complet, de comparer les passages aux semaines prÃ©cÃ©dentes et d'identifier les pÃ©riodes de panne.

- Le calendrier est complÃ©tÃ© avec `generate_series`.
- Une heure sans mesure reste une valeur manquante et n'est jamais remplacÃ©e automatiquement par zÃ©ro.
- Q2 compare les mesures aux quatre semaines prÃ©cÃ©dentes Ã  partir du calendrier horaire.
- Q3 utilise une vue matÃ©rialisÃ©e du calendrier, triÃ©e et indexÃ©e, pour rÃ©duire le coÃ»t des traitements.

L'optimisation de Q3 a permis de rÃ©duire le temps d'exÃ©cution mesurÃ© d'environ **2,6 secondes Ã  1,3 seconde**. Les mesures sont dÃ©taillÃ©es dans [`docs/optimisation.md`](docs/optimisation.md).

### Calcul de l'indice

Le calcul de l'indice repose sur les rÃ¨gles suivantes :

- Les compteurs vÃ©lo situÃ©s Ã  moins de 800 mÃ¨tres du lieu sont rattachÃ©s Ã  l'Ã©vÃ©nement.
- La fenÃªtre observÃ©e couvre l'heure prÃ©cÃ©dant le dÃ©but de l'Ã©vÃ©nement jusqu'Ã  l'heure suivant sa fin.
- La rÃ©fÃ©rence utilise les mÃªmes crÃ©neaux horaires et le mÃªme jour de la semaine sur les quatre semaines prÃ©cÃ©dentes.
- Les semaines perturbÃ©es par un autre Ã©vÃ©nement proche ou par une panne sont exclues.
- Si aucun capteur ou aucune rÃ©fÃ©rence exploitable n'est disponible, l'indice reste NULL.

Un indice NULL n'est donc jamais assimilÃ© Ã  une valeur Ã©gale Ã  zÃ©ro.

## RÃ©sultats et limites de l'indice

L'indice mesure l'Ã©volution des passages enregistrÃ©s par les compteurs vÃ©lo situÃ©s Ã  proximitÃ© des lieux d'Ã©vÃ©nements. Il ne mesure ni le nombre de participants Ã  un Ã©vÃ©nement, ni la part des participants qui se dÃ©placent Ã  vÃ©lo.

### Couverture des Ã©vÃ©nements

Sur les 6 176 Ã©vÃ©nements retenus dans l'analyse de couverture :

| CatÃ©gorie | Nombre | Part |
|---|---:|---:|
| Lieu sans coordonnÃ©es exploitables | 4 | 0,1 % |
| Aucun capteur Ã  proximitÃ© | 3 158 | 51,1 % |
| Compteur disponible, mais aucun indice calculable | 1 600 | 25,9 % |
| Au moins un indice calculÃ© | 1 414 | 22,9 % |

La vue des indices contient 53 852 lignes, dont 5 147 avec un indice non nul. Une ligne correspond Ã  une mesure pour un Ã©vÃ©nement, une occurrence et un compteur : ce nombre ne reprÃ©sente donc pas le nombre d'Ã©vÃ©nements.

### Top 10 des Ã©vÃ©nements

Le classement R3 fait apparaÃ®tre notamment :

| Ã‰vÃ©nement | Lieu | Indice moyen |
|---|---|---:|
| Tom Boudet vous dit quoi | ThÃ©Ã¢tre Ã  l'Ouest | 4,99 |
| Surprise : partie ! | ThÃ©Ã¢tre Ã  l'Ouest | 4,43 |
| Dessiner Flaubert : Rochegrosse | MusÃ©e Flaubert et d'histoire de la mÃ©decine | 4,36 |
| FC Rouen - ChÃ¢teauroux | Stade Pierre LefranÃ§ois | 4,25 |
| Foire Ã  tout du 14 juillet | Place Saint-Michel | 3,70 |

Ces valeurs indiquent une frÃ©quentation cyclable observÃ©e supÃ©rieure Ã  la rÃ©fÃ©rence sur les crÃ©neaux Ã©tudiÃ©s. Elles ne permettent pas d'attribuer toute cette hausse au seul Ã©vÃ©nement.

### Limites mÃ©thodologiques

- **RÃ©fÃ©rence parfois absente :** la mÃ©thode Ã©carte les semaines oÃ¹ un autre Ã©vÃ©nement a lieu dans la zone. Cela peut rÃ©duire le nombre de semaines de rÃ©fÃ©rence disponibles et empÃªcher le calcul de certains indices.
- **Ã‰vÃ©nements simultanÃ©s :** les passages de plusieurs Ã©vÃ©nements proches peuvent se cumuler. L'indice mesure la frÃ©quentation de la zone pendant l'Ã©vÃ©nement, et non l'effet isolÃ© de celui-ci.
- **Jours fÃ©riÃ©s et vacances :** les semaines de rÃ©fÃ©rence ne tiennent pas nÃ©cessairement compte de toutes les particularitÃ©s du calendrier.
- **Zone circulaire :** un compteur situÃ© Ã  moins de 800 mÃ¨tres peut se trouver sur un axe qui ne dessert pas directement le lieu.
- **DisponibilitÃ© des compteurs :** les pannes et les donnÃ©es manquantes rÃ©duisent les possibilitÃ©s de calcul.
- **LovÃ©lo non intÃ©grÃ© :** cette version repose uniquement sur les compteurs Eco-counter. Les stations LovÃ©lo n'ont pas Ã©tÃ© intÃ©grÃ©es Ã  l'analyse.

Ces rÃ©sultats doivent Ãªtre interprÃ©tÃ©s comme un indicateur de variation de la frÃ©quentation cyclable Ã  proximitÃ© des Ã©vÃ©nements, et non comme une mesure directe de leur frÃ©quentation.

## Usage dÃ©clarÃ© de l'IA

| Partie | Outil | Usage |
|---|---|---|
| Mise en place du dÃ©pÃ´t, arborescence et documentation | Claude Code | GÃ©nÃ©ration du squelette initial Ã  partir du kit |
| Profilage des sources | Claude Code | Aide Ã  la rÃ©alisation du script et Ã  la documentation, avec relecture des rÃ¨gles |
| Chargement des comptages | Claude Code | Aide aux corrections du chargement et aux tests associÃ©s |
| Collecte, nettoyage et pipeline ETL | ChatGPT | Assistance Ã  la conception, Ã  l'explication, au dÃ©bogage et Ã  la rÃ©daction du code, avec exÃ©cution et vÃ©rification des rÃ©sultats par le membre du groupe |
| Export Parquet et publication Hugging Face | ChatGPT | Assistance Ã  la rÃ©alisation du script d'export et de publication, avec vÃ©rification des volumes et du dÃ©pÃ´t publiÃ© |
| Documentation et README | ChatGPT | Assistance Ã  la rÃ©daction et Ã  la mise Ã  jour de la documentation |

Les outils d'IA ont Ã©tÃ© utilisÃ©s comme assistance. Les choix techniques, les tests et les rÃ©sultats doivent Ãªtre compris et expliquÃ©s par les membres du groupe.

Chaque membre du groupe doit Ãªtre en mesure d'expliquer le fonctionnement gÃ©nÃ©ral du projet et les traitements rÃ©alisÃ©s.
