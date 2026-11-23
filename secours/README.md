# Jeux de secours : travailler même si une API est indisponible

Les TP et le fil rouge s'appuient sur des API externes (OpenAgenda, portail open data de la Métropole, Lovélo,
HuggingFace). Si l'une d'elles est lente, en panne ou bloquée par le réseau de l'école, **on bascule en local
sans changer le code** : un serveur local imite ces API à partir de données enregistrées.
**La note ne dépend jamais de la disponibilité d'une API.**

## Deux jeux de données

| Dossier | Contenu | Origine |
|---|---|---|
| `secours/reel/` | Photographie des vraies sources (événements OpenAgenda, comptages vélo, Lovélo, extraits Amazon Reviews) | Préparé par l'intervenante avant le module (`preparer_secours.py`), distribué sur clé USB / drive |
| `secours/synthetique/` | Données **fictives** de même forme, avec les mêmes défauts à nettoyer | Déjà dans le kit ; se régénère avec `python secours/generer_synthetique.py` |

Le serveur prend `reel/` s'il existe, sinon `synthetique/`.

## Basculer en local (2 minutes)

```bash
# 1. Dans un premier terminal, laisser tourner :
python secours/serveur_api_local.py

# 2. Dans le terminal de travail :
export OA_API=http://localhost:8765/openagenda/v2
export OA_KEY=secours                         # la clé n'est pas vérifiée en local
export PORTAIL_API=http://localhost:8765/ods/api/explore/v2.1/catalog/datasets
export HF_ROWS_API=http://localhost:8765/hf/rows
export AMAZON_LOCAL_DIR=secours/reel          # Amazon Reviews depuis les fichiers locaux (TP0, TP4)
```

Windows PowerShell : `$env:OA_API="http://localhost:8765/openagenda/v2"` (idem pour les autres).

| Besoin | Commande en mode secours |
|---|---|
| TP0 : charger Amazon Reviews | `AMAZON_LOCAL_DIR=secours/reel python scripts/load_to_postgres.py --category All_Beauty` |
| TP3 : collecteur asynchrone | inchangée (variable `HF_ROWS_API`) |
| TP4 : streaming et échantillon | inchangées (variable `AMAZON_LOCAL_DIR`) |
| Fil rouge : comptages vélo | `python chargement/load_comptages.py --file secours/synthetique/eco-counter-data.csv` (ou via `PORTAIL_API`) |
| Fil rouge : événements | `python collecte/openagenda_collector.py` (variable `OA_API`) ou directement `secours/<jeu>/evenements_bruts.jsonl` |
| Fil rouge : Lovélo | `python collecte/lovelo_collector.py --gbfs-url http://localhost:8765/gbfs/gbfs.json` |

## Bonus pédagogique : simuler les pannes

```bash
python secours/serveur_api_local.py --taux-429 0.1 --taux-503 0.05 --latence-ms 150
```

10 % des requêtes reçoivent un 429 (avec `Retry-After`), 5 % un 503, et chaque réponse est retardée :
c'est le meilleur moyen de vérifier que vos retries et votre reprise fonctionnent vraiment (TP3, fil rouge).

## À savoir

- Les données synthétiques sont **fictives** : les résultats (top 10 des événements, indice) n'ont pas de sens
  réel. Indiquez dans le README et la Dataset Card du projet quel jeu a été utilisé.
- Les données Amazon ne sont pas générées en synthétique : sans `secours/reel/`, le TP3 utilise des avis fictifs
  servis par le serveur local, et TP0/TP4 nécessitent le jeu réel préparé par l'intervenante.
