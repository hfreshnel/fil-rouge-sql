# Profilage des sources

Pour chaque source : anomalies constatées et règle explicite appliquée (rejet, correction ou signalement).

**Jeux utilisés**
- Comptages vélo : **réel**, portail de la Métropole (`eco-counter-data`, téléchargé le 24/11/2026).
- Événements et référentiel des lieux : **synthétique** du kit (`secours/synthetique/`, données fictives). Le collecteur OpenAgenda arrive en séance 4 ; ces chiffres seront à refaire sur le jeu réel.

Commande : `python chargement/profilage.py` (ou `comptages`, `evenements`, `lieux` pour une seule source).

**Rappel des règles**
- **Rejet** : la ligne est écartée et part en quarantaine avec sa raison.
- **Correction** : la valeur est réparée au chargement ou au nettoyage.
- **Signalement** : la ligne est gardée, avec un indicateur.

## Comptages vélo (`eco-counter-data`)

1 058 116 lignes, 35 compteurs, du 31/12/2021 au 23/11/2026.

| Anomalie | Exemple / volume | Règle (rejet · correction · signalement) |
|---|---|---|
| Pas de colonnes lat/lon : coordonnées dans `location`, en binaire WKB | 35 compteurs sur 35 ; ex. Eco 26 - Avenue Pasteur → (49.4431, 1.0781) | **Correction** : décodage de `location` en lat/lon au chargement. Les 35 se décodent et sont toutes dans la Métropole. |
| `status` en deux formats mélangés (texte et liste JSON) | « Donnée brut » 1 039 010 (98,2 %) · « Donnée corrigée » 13 226 (1,25 %) · `["validated"]` 5 870 (0,55 %) | **Correction** : normalisation en 3 valeurs (`brut`, `corrige`, `valide`), conservées dans une colonne. |
| Lignes marquées supprimées, sans comptage | 10 lignes (0,001 %) : `["deleted", "validated"]` × 9, `["modified", "deleted"]` × 1. Ce sont exactement les 10 comptages vides. | **Rejet** (quarantaine, raison « supprimée à la source »). |
| Doublon (même compteur, même heure) | 1 cas : Eco 29 - Avenue Mont Riboudet, 30/03/2025 01:00 UTC, une ligne `deleted` vide et une ligne « Donnée corrigée » à 4 | **Correction** : une seule ligne par (compteur, heure), on garde la ligne non supprimée. Le chargement fourni **additionne** les lignes d'une même heure : à remplacer par un dédoublonnage. |
| Heures manquantes (lignes absentes) | 9 712 heures (0,9 %) ; pire cas Eco 37 - Pont Boieldieu : 2 226 h (23,7 %), dont un trou de 87 jours | **Signalement** : heure à NULL dans le calendrier complet (Q1), jamais remplacée par 0. Une heure absente ne compte pas dans la référence de l'indice. |
| Pannes probables : 24 h consécutives ou plus à 0 | 33 séries, 5 073 heures (0,5 %), 9 compteurs ; ex. Eco 22 - Rte de Paris à 0 du 15/08 au 25/10/2025 (1 710 h) | **Signalement** : période marquée en panne (Q4) et **exclue du calcul de l'indice**. |
| Colonnes inutiles ou redondantes | `travel_mode` : une seule valeur (« Vélo ») · `annee` : 1er janvier de l'année (2022-01-01…) · `date_j` : toujours égale au jour de `date` en heure de Paris · `photourl` : 4 compteurs ont 2 photos | **Correction** : colonnes ignorées au chargement. |

Vérifié sans anomalie :
- comptages négatifs ou non entiers : 0 ;
- dates illisibles ou pas pile sur l'heure : 0 ;
- `date` est déjà en UTC ;
- pics suspects (plus de 5 × le 99e centile du compteur) : 0.

Les 239 978 heures à 0 (22,7 %) sont surtout des heures de nuit. Seules les séries de 24 h ou plus sont traitées comme des pannes.

## Événements OpenAgenda

3 135 lignes, jeu synthétique.

| Anomalie | Exemple / volume | Règle (rejet · correction · signalement) |
|---|---|---|
| Même `uid` présent plusieurs fois (mises à jour) | 75 uid, 75 lignes en trop (2,4 %), aucune copie exacte (`updatedAt` différent) ; ex. uid 907748 | **Correction** : on garde la version la plus récente (`updatedAt`). |
| Même événement sous deux `uid` (même titre, même lieu, même 1re date) | 60 cas ; ex. « Conférence de la Seine », uid 902490 et 910751 | **Rejet** du doublon (quarantaine, raison « doublon »), on en garde un. |
| Aucune date (`timings` vide) | 39 (1,2 %) ; ex. uid 905207 | **Rejet**. |
| Toutes les occurrences avec fin < début | 55 (1,8 %) ; ex. début 13:00, fin 10:00 le 10/02/2025 | **Rejet**. |
| Titre vide une fois le HTML retiré | 20 (0,6 %) ; ex. `{"fr": "  <br/> "}` | **Rejet**. |
| Titre sans version française | 298 (9,5 %), titre en anglais seulement ; ex. `{"en": "Conférence de la Seine"}` | **Correction** : on prend la langue disponible (`text_fr`). |
| Balises HTML dans la description | 1 570 (50,1 %) ; ex. `<p>… <b>à ne pas manquer` | **Correction** : balises retirées, espaces normalisés. |
| Entités HTML dans la description | 1 589 (50,7 %) ; ex. `&amp;` | **Correction** : entités décodées (`html.unescape`). |
| Description absente | 758 (24,2 %) | **Correction** : chaîne vide. L'indice n'utilise pas la description, donc pas de rejet. |
| Mots-clés en double (casse, espaces) | 651 (20,8 %) ; ex. `["sport", "sport "]` | **Correction** : minuscules, espaces retirés, sans doublons. |
| Coordonnées hors de la Métropole | 63 (2,0 %) ; ex. Hangar 23 à (48.8566, 2.3522), c'est-à-dire Paris | **Correction** : coordonnées mises à NULL (pas de rejet), puis reprises du référentiel ou géocodées via la BAN. |
| Lieu sans coordonnées | 158 (5,0 %) ; ex. Zénith de Rouen | **Correction** : coordonnées reprises du référentiel des lieux ou de la BAN. |
| Même lieu saisi sous plusieurs noms | 22 noms différents ; ex. « Le 106 », « Le106 », « le 106 - SMAC », « Le 106 – Salle des Musiques Actuelles » | **Correction** : nom normalisé et rapprochement approximatif avec le référentiel (même ville). |
| Événements annulés, complets ou reprogrammés | statut 6 annulé : 302 (9,6 %) · 5 complet : 294 · 2 reprogrammé : 260 · 1 programmé : 2 279 | **Signalement** : statut conservé ; les annulés sont exclus de l'indice (l'événement n'a pas eu lieu). ⚠ Le dictionnaire `STATUS` de `transform/clean_events.py` donne 5 = annulé, alors que la doc OpenAgenda donne 5 = complet et 6 = annulé : à vérifier et à corriger. |

## Référentiel des lieux

15 lieux, jeu synthétique.

| Anomalie | Exemple / volume | Règle (rejet · correction · signalement) |
|---|---|---|
| Lieux de l'agenda sans correspondance exacte dans le référentiel | 5 noms sur 22 (315 événements, 10,0 %) : « Opéra de Rouen - Théâtre des Arts », « Le106 », « Palais des sports Kindarena », « le 106 - SMAC », « Le 106 » | **Correction** : rapprochement approximatif (nom normalisé, même ville, seuil de similarité). Sous le seuil, **signalement** : le lieu est ajouté avec `source = 'openagenda'`. |

Vérifié sans anomalie : aucun lieu sans nom, sans ville ou sans coordonnées ; aucune coordonnée hors de la Métropole ; aucun doublon.

## Lovélo (bonus)

Non profilé pour l'instant : le flux GBFS doit d'abord être collecté (`collecte/lovelo_collector.py`).

| Anomalie | Exemple / volume | Règle (rejet · correction · signalement) |
|---|---|---|
| | | |
