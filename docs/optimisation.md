# Optimisation de Q2 (Q3)

Requête mesurée : Q2 (`sql/fr_02_requetes_metier.sql`), sur toute la table `counts_hourly`.
Volume : **1 058 106 lignes** (220 Mo avec l'index), **35 compteurs**, soit **1 067 818 heures** dans le calendrier complet.

Mesures reproductibles : `psql -h localhost -U etl -d metropole -f sql/q3_mesure.sql`.
PostgreSQL 17, `work_mem` = 32 MB, cache chaud. Chaque requête est lancée 3 fois ; les plans ci-dessous sont ceux de la 3ᵉ exécution.

## Plan avant

Q2 calculée sur `v_calendrier` : le calendrier est reconstruit à chaque appel.

```
EXPLAIN (ANALYZE, BUFFERS) <Q2 sur v_calendrier>
 Subquery Scan on semaines  (cost=86787.74..89675.21 rows=35000 width=90) (actual time=1364.280..2568.838 rows=1067818 loops=1)
   Buffers: shared hit=35288, temp read=10672 written=10674
   I/O Timings: temp read=11.290 write=43.484
   ->  WindowAgg  (cost=86787.74..87750.21 rows=35000 width=38) (actual time=1364.275..2021.677 rows=1067818 loops=1)
         Buffers: shared hit=35288, temp read=10672 written=10674
         I/O Timings: temp read=11.290 write=43.484
         ->  Sort  (cost=86787.71..86875.21 rows=35000 width=22) (actual time=1364.260..1506.647 rows=1067818 loops=1)
               Sort Key: counts_hourly.counter_id, h.ts
               Sort Method: external merge  Disk: 39680kB
               Buffers: shared hit=35288, temp read=10672 written=10674
               I/O Timings: temp read=11.290 write=43.484
               ->  Hash Left Join  (cost=76641.28..84146.08 rows=35000 width=22) (actual time=364.329..924.610 rows=1067818 loops=1)
                     Hash Cond: ((counts_hourly.counter_id = c.counter_id) AND (h.ts = c.ts))
                     Buffers: shared hit=35288, temp read=5712 written=5712
                     I/O Timings: temp read=6.392 write=23.905
                     ->  Nested Loop  (cost=26352.63..27061.68 rows=35000 width=18) (actual time=65.307..214.340 rows=1067818 loops=1)
                           Buffers: shared hit=17652
                           ->  Finalize GroupAggregate  (cost=26352.63..26361.67 rows=35 width=26) (actual time=63.331..63.699 rows=35 loops=1)
                                 Group Key: counts_hourly.counter_id
                                 Buffers: shared hit=17652
                                 ->  Gather Merge  (cost=26352.63..26360.80 rows=70 width=26) (actual time=63.323..63.581 rows=105 loops=1)
                                       Workers Planned: 2
                                       Workers Launched: 2
                                       Buffers: shared hit=17652
                                       ->  Sort  (cost=25352.61..25352.70 rows=35 width=26) (actual time=61.421..61.433 rows=35 loops=3)
                                             Sort Key: counts_hourly.counter_id
                                             Sort Method: quicksort  Memory: 26kB
                                             Buffers: shared hit=17652
                                             Worker 0:  Sort Method: quicksort  Memory: 26kB
                                             Worker 1:  Sort Method: quicksort  Memory: 26kB
                                             ->  Partial HashAggregate  (cost=25351.36..25351.71 rows=35 width=26) (actual time=61.383..61.388 rows=35 loops=3)
                                                   Group Key: counts_hourly.counter_id
                                                   Batches: 1  Memory Usage: 24kB
                                                   Buffers: shared hit=17636
                                                   Worker 0:  Batches: 1  Memory Usage: 24kB
                                                   Worker 1:  Batches: 1  Memory Usage: 24kB
                                                   ->  Parallel Seq Scan on counts_hourly  (cost=0.00..22044.78 rows=440878 width=18) (actual time=1.298..16.918 rows=352702 loops=3)
                                                         Buffers: shared hit=17636
                           ->  Function Scan on generate_series h  (cost=0.00..10.00 rows=1000 width=8) (actual time=1.278..2.293 rows=30509 loops=35)
                     ->  Hash  (cost=28217.06..28217.06 rows=1058106 width=22) (actual time=296.331..296.332 rows=1058106 loops=1)
                           Buckets: 1048576  Batches: 2  Memory Usage: 37120kB
                           Buffers: shared hit=17636, temp written=2842
                           I/O Timings: temp write=7.735
                           ->  Seq Scan on counts_hourly c  (cost=0.00..28217.06 rows=1058106 width=22) (actual time=3.018..72.010 rows=1058106 loops=1)
                                 Buffers: shared hit=17636
 Planning Time: 0.005 ms
 Execution Time: 2601.432 ms
```

### Ce que montre le plan (à lire de bas en haut)

1. **`counts_hourly` est lue deux fois** : une fois pour les bornes de chaque compteur (`Parallel Seq Scan` puis `HashAggregate`), une fois pour la jointure (`Seq Scan on counts_hourly c`).
2. **Estimation fausse d'un facteur 30** : `generate_series` est estimé à 1 000 lignes par appel (valeur par défaut de PostgreSQL pour une fonction), soit 35 × 1 000 = `rows=35000`, alors qu'il en sort 30 509 en moyenne (`rows=30509 loops=35`), soit 1 067 818. Toute la suite du plan est choisie pour 35 000 lignes.
3. **Le hachage et le tri débordent sur disque** : la table de hachage de la jointure est coupée en 2 lots (`Batches: 2`, `temp written=2842`) et le tri par `(counter_id, ts)` dont `LAG` a besoin se fait sur disque (`Sort Method: external merge  Disk: 39680kB`). Ils dépassent `work_mem`.
4. Le tri seul coûte ~580 ms (de 924 à 1 506 ms), la reconstruction du calendrier ~920 ms.

## Optimisation proposée : vue matérialisée du calendrier

```sql
CREATE MATERIALIZED VIEW mv_calendrier AS
    SELECT counter_id, ts, passages FROM v_calendrier ORDER BY counter_id, ts;
CREATE UNIQUE INDEX mv_calendrier_cle ON mv_calendrier (counter_id, ts);
```

Puis `v_comparaison_4sem` lit `mv_calendrier` au lieu de `v_calendrier`.

**Pourquoi cette optimisation :**
- Le calendrier complet est la partie la plus chère (double lecture, jointure, tri), et il **ne change qu'au chargement** des comptages : inutile de le recalculer à chaque requête.
- Il est réutilisé par Q2, Q4 et l'indice (`fr_03`) : on paie une fois, on gagne à chaque fois.
- Stocké **dans l'ordre** `(counter_id, ts)` et indexé sur cette clé, il est relu **déjà trié** : plus de tri pour `LAG`.
- Une vue matérialisée a de vraies statistiques (`ANALYZE`) : l'estimation devient exacte.

**Pistes écartées :**

| Piste | Résultat | Pourquoi on ne la retient pas |
|---|---|---|
| Augmenter `work_mem` à 256 MB | 2 211 ms (−8 %) | Le tri tient en mémoire, mais la double lecture et la jointure restent ; ~170 Mo de RAM par requête |
| Index sur `counts_hourly (counter_id, ts)` | — | Il existe déjà : c'est la clé primaire. Le coût vient du calendrier reconstruit, pas de la recherche |
| Partitionnement par mois | non testé | Utile pour filtrer une période ; Q2 lit toute la table, donc toutes les partitions |
| Matérialiser `v_comparaison_4sem` entière | non retenu | Gain maximal, mais on stocke le résultat au lieu d'accélérer le calcul ; à rafraîchir aussi |

## Plan après

```
EXPLAIN (ANALYZE, BUFFERS) SELECT * FROM v_comparaison_4sem;
 Subquery Scan on semaines  (cost=0.50..140836.82 rows=1067818 width=90) (actual time=5.034..1269.820 rows=1067818 loops=1)
   Buffers: shared hit=13107
   ->  WindowAgg  (cost=0.50..82106.83 rows=1067818 width=38) (actual time=5.030..741.042 rows=1067818 loops=1)
         Buffers: shared hit=13107
         ->  Index Scan using mv_calendrier_cle on mv_calendrier  (cost=0.43..55411.38 rows=1067818 width=22) (actual time=0.012..126.131 rows=1067818 loops=1)
               Buffers: shared hit=13107
 Planning Time: 0.113 ms
 JIT:
   Functions: 17
   Options: Inlining false, Optimization false, Expressions true, Deforming true
   Timing: Generation 0.753 ms (Deform 0.265 ms), Inlining 0.000 ms, Optimization 0.230 ms, Emission 4.780 ms, Total 5.764 ms
 Execution Time: 1298.312 ms
```

Plus que 3 nœuds : un `Index Scan` qui livre les lignes déjà triées, puis `WindowAgg` (les 4 `LAG`). Plus de `Sort`, plus de `Hash`, plus de fichiers temporaires, et l'estimation est exacte (`rows=1067818`).
Les ~530 ms restants au-dessus de `WindowAgg` sont le calcul de la moyenne et de l'indice en `numeric`.

## Gain

| Mesure | Avant | Après | Gain |
|---|---|---|---|
| Temps d'exécution (3 mesures) | 2 729 / 2 631 / 2 601 ms | 1 277 / 1 275 / 1 298 ms | **−51 %** (÷ 2,0) |
| Buffers (shared hit / read) | 35 288 / 0 | 13 107 / 0 | −63 % de pages lues |
| Fichiers temporaires (temp read / written) | 10 672 / 10 674 pages (~83 Mo) | 0 / 0 | supprimés |
| Tri | `external merge`, 39 680 kB sur disque | aucun | supprimé |
| Lignes estimées / réelles | 35 000 / 1 067 818 | 1 067 818 / 1 067 818 | estimation exacte |

## Coût de l'optimisation

- **Rafraîchissement** : `REFRESH MATERIALIZED VIEW mv_calendrier` prend ~4,5 s (calendrier + index). Il est lancé par `chargement/load_comptages.py` après chaque chargement, et par `sql/fr_02_requetes_metier.sql`.
- **Fraîcheur** : entre deux rafraîchissements, la vue ne voit pas les nouveaux comptages. Acceptable ici : les comptages sont chargés en lot, pas en continu.
- **Place** : 62 Mo de table + 41 Mo d'index (contre 220 Mo pour `counts_hourly`).
- Le rafraîchissement est rentable dès 4 exécutions de Q2 (4,5 s ÷ 1,3 s gagnée), sans compter Q4 et l'indice qui en profitent aussi.
