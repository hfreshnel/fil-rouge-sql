# Optimisation de Q2 (Q3)

Requête mesurée : Q2 (`sql/fr_02_requetes_metier.sql`), sur toute la table `counts_hourly`.
Volume : _N lignes, M compteurs_

## Plan avant

```
EXPLAIN (ANALYZE, BUFFERS) ...
```

## Optimisation proposée

_Index / réécriture / partitionnement par mois / vue matérialisée — justification._

## Plan après

```
EXPLAIN (ANALYZE, BUFFERS) ...
```

## Gain

| Mesure | Avant | Après | Gain |
|---|---|---|---|
| Temps d'exécution | | | |
| Buffers (shared hit / read) | | | |
