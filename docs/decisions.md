# Décisions techniques

Chaque décision : **choix** → **pourquoi** → **alternative écartée**.

---

## D1 — Règles explicites, pas de machine learning
- **Choix** : décision par règles, seuils dans `config/rules.yaml`.
- **Pourquoi** : pas de dossiers annotés ; une décision juridique doit être explicable, reproductible et défendable devant un juge.
- **Écarté** : un classifieur supervisé. À reconsidérer avec un historique de dossiers et leur issue, pour **calibrer** les seuils, pas pour remplacer les règles.

## D2 — Le LLM est hors de la décision
- **Choix** : l'explication est un texte construit à partir des preuves. Un LLM la reformule en note pour le juriste, uniquement à partir du JSON, avec des contrôles (D14).
- **Pourquoi** : « le code décide, l'IA met en forme ». Une décision non reproductible n'est pas défendable.
- **Écarté** : demander à un LLM « y a-t-il une circonstance extraordinaire ? ».

## D3 — Source météo : METAR historiques de l'Iowa Environmental Mesonet
- **Choix** : archive gratuite, champs déjà décodés, METAR brut conservé comme preuve.
- **Écarté** : écrire un décodeur METAR (risque de bugs) ; une API payante (inutile pour un prototype). L'interface `get_observations` permet de changer de source sans toucher au moteur.

## D4 — Dossiers de test : journée réelle, vol fictif
- **Choix** : météo et événements réels et sourcés, vol construit et signalé comme tel.
- **Pourquoi** : en Europe, les horaires prévus des vols ne sont pas en accès libre (OpenSky n'a que des heures estimées ; les historiques d'horaires sont commerciaux).
- **Complément prévu** : une évaluation chiffrée sur les retards Eurocontrol par aéroport, par jour et par cause. **Pas encore faite** : l'étape 4 s'appuie sur 13 dossiers annotés à la main (D13).

## D5 — Seuils de départ (hypothèses)
| Critère | Modéré | Sévère | Repère |
|---|---|---|---|
| Rafales | ≥ 35 kt | ≥ 50 kt | Gêne au décollage et à l'atterrissage / niveau tempête |
| Vent moyen | ≥ 25 kt | — | |
| Visibilité | < 550 m | < 150 m | 550 m : minimum d'une approche de catégorie I |
| Plafond | < 200 ft | — | 200 ft : hauteur de décision d'une approche de catégorie I |
| Neige | `SN` | `+SN` | `-SN` (faible) ignorée |
| Orage | `TS` | `+TS` | |
| Verglaçant, grêle, grain, trombe, cendres | — | toujours | |

Ce sont des repères opérationnels, **pas des seuils légaux**. À valider avec les juristes.

## D6 — La durée compte, pas seulement l'intensité
- **Choix** : une CE météo est retenue si ≥ 30 min de conditions sévères, **ou** ≥ 3 h de conditions modérées.
- **Pourquoi** : à Munich, le 2 décembre 2023, il n'y a ni vent ni visibilité catastrophique, mais un plafond à 100 ft et de la neige pendant des heures. Un seuil d'intensité seul aurait raté la fermeture de l'aéroport.

## D7 — Seuils asymétriques et actions
| Statut | Condition | Action |
|---|---|---|
| `AUCUNE` | aucun signal, données météo complètes **et** calendrier des grèves couvrant les deux aéroports | `CONTINUER` (automatique) |
| `EC_PROBABLE` | épisode de CE, qui explique le retard | `MISE_EN_ATTENTE` |
| `EC_PROBABLE` | épisode de CE, qui n'explique pas tout le retard | `RELECTURE_JURISTE` |
| `INCERTAIN` | signaux faibles, données incomplètes, panne, régime non géré, grève non confirmée ou hors couverture du calendrier | `RELECTURE_JURISTE` |

Le seul chemin automatique (`CONTINUER`) est aussi le plus exigeant.

## D8 — Le statut et les minutes expliquées sont séparés
- **Choix** : le statut répond à « y a-t-il une CE plausible ? ». Les minutes expliquées répondent à « combien de retard couvre-t-elle ? ».
- **Pourquoi** : la détection est fiable, l'imputation du retard est une approximation. On ne laisse pas une approximation faible dégrader un signal fiable. Mais si la CE n'explique pas tout le retard (C-108/26 : on déduit le temps imputable), le dossier part chez un juriste.
- **Approximation** : chevauchement entre [début de l'épisode, fin + 2 h de remise en état] et [heure prévue, heure réelle].

## D9 — Une panne ou un trou de données ne donne jamais `AUCUNE`
- **Choix** : trou de plus de 90 min, aucun relevé, ou erreur de la source → `INCERTAIN`.
- **Pourquoi** : l'absence de preuve n'est pas la preuve de l'absence.

## D10 — Le régime juridique dépend de la date du vol
- **Choix** : vol à partir du 23 octobre 2027 → `INCERTAIN` (règlement 2026/2202 non implémenté).
- **Pourquoi** : mieux vaut refuser de conclure qu'appliquer de mauvaises règles.

## D11 — La confiance est un niveau fixé par règle
- **Choix** : 0,9 / 0,75 / 0,5 selon la règle déclenchée.
- **Pourquoi** : sans données annotées, présenter une probabilité calibrée serait trompeur. Ce champ pourra être calibré plus tard.
## D12 — Grèves ATC : calendrier sourcé, avec couverture déclarée
- **Choix** : `data/strikes.yaml` liste les grèves (statut, zone OACI, aéroports cités par une source, période, syndicats, sources) **et** les zones et périodes vérifiées (`coverage`). Pour chaque aéroport :
  | Situation | Résultat |
  |---|---|
  | Grève confirmée, aéroport cité par une source | `EC_PROBABLE`, type `GREVE_ATC` |
  | Grève confirmée dans la zone, aéroport non cité | `INCERTAIN` |
  | Préavis seulement (`announced`) | `INCERTAIN` |
  | Préavis annulé (`cancelled`) | ignoré (gardé pour la traçabilité) |
  | Zone ou période non couverte, calendrier illisible | `INCERTAIN` |
- **Pourquoi** : un calendrier manuel est forcément incomplet. Sans couverture déclarée, « pas dans le calendrier » deviendrait « pas de grève », puis `CONTINUER` : l'erreur la plus coûteuse (D9).
- **Imputation** : à la journée. Les horaires précis des préavis ne sont pas sourcés, donc une grève confirmée explique tout le retard qui tombe dans la journée, et le dossier passe en `MISE_EN_ATTENTE`. **À valider avec les juristes** : on pourrait préférer `RELECTURE_JURISTE` tant que les horaires ne sont pas précis.
- **Confiance** : 0,8 (`confidence.ec_strike_confirmed`), sous la météo sévère : la grève est sûre, son lien avec ce vol précis l'est moins.
- **Météo et grève ensemble** : les deux types sont gardés (`ec_types`), avec leurs preuves. Le type principal est celui qui explique le plus de minutes. Une grève confirmée n'est pas masquée par un trou dans les données météo.
- **Écarté** : un LLM qui lit la presse pour décider s'il y a grève. Il peut proposer des entrées au calendrier, un humain les valide (D2).

## D13 — Évaluation : trois classes, et l'automatisation mesurée à part
- **Choix** : `expected.status` est l'étiquette de vérité. Chaque dossier est `CORRECT`, `RENVOYE` (le module dit `INCERTAIN` alors que la vérité est tranchée) ou `FAUX`. On mesure à part la part traitée sans humain (`CONTINUER` ou `MISE_EN_ATTENTE`) et le taux d'erreur parmi elle, avec les erreurs critiques (`CONTINUER` sur une CE plausible) isolées.
- **Pourquoi** : ce sont les deux indicateurs du produit. Un renvoi coûte du temps de juriste, une erreur automatique coûte un procès ou un dossier.
- **Protocole** : étiquette, horaires (convention fixe : départ 10:00Z, 210 min de retard) et sources écrits **avant** de lancer le moteur. Un écart est un résultat, pas une raison de modifier le dossier ou un seuil.
- **Limite** : 13 dossiers, dont des pièges choisis à la main. Démonstration, pas une mesure statistique.

## D14 — Note pour le juriste : un LLM rédige, le code vérifie
- **Choix** : `src/ec_detector/note.py`. Après la décision, un LLM (Mistral, `ministral-8b-latest` par défaut) rédige une note de 3 paragraphes pour le juriste. Endpoint `POST /api/note`, bouton « Rédiger la note (IA) » dans l'interface.
- **Ce que reçoit le LLM** : uniquement des **faits** extraits du JSON de décision, chacun avec un identifiant : `D1` (décision), `V1` (vol), `R1`, `R2`… (raisons du moteur) et `E1`, `E2`… (preuves, 20 au plus, réparties entre les aéroports). Le code ajoute le **sens** de la décision en clair (« la compagnie pourrait refuser l'indemnité… ») et le nom des aéroports. Ni donnée passager, ni décision envoyée par le navigateur : le serveur recalcule la décision avant d'écrire la note.
- **Ce que vérifie le code**, avant d'afficher la note :
  | Contrôle | Pourquoi |
  |---|---|
  | Réponse en JSON au format attendu | pas de texte libre non structuré |
  | Chaque paragraphe cite au moins une référence | pas d'affirmation sans preuve |
  | Chaque référence existe (`D1`, `V1`, `R…`, `E…` envoyés) | pas de preuve inventée |
  | Chaque nombre du texte figure dans les faits | pas de durée, date ou vitesse inventée ou mal convertie |
  | Pas de formulation qui inverse la décision (« indemnisation probable » sur une CE probable…), négations comprises | le pire défaut : une note qui dit le contraire du moteur |
  | Pas de code OACI ni de ville absents des faits | pas de « LFPG (Paris-Orly) » |
- **Forme corrigée, fond jamais** : « raisons.R3 » devient `R3`, « E1-E3 » devient `E1, E2, E3`, le gras Markdown est retiré. Une référence qui n'existe pas reste refusée.
- **Mise au point sur de vraies réponses** : les premières notes de `ministral-8b` citaient des références au mauvais format, inversaient le sens (« confirme une indemnisation probable » sur une grève) et inventaient des noms d'aéroports. Chacune de ces erreurs est devenue un test (`tests/test_note.py`) et un contrôle.
- **Repli** : sans clé, en cas d'erreur réseau, de quota ou de contrôle échoué, la note vient du **modèle fixe**, au même format. La raison du repli et les problèmes détectés sont affichés. Un échec passager (quota, réseau) n'est pas mis en cache et peut être retenté. La démonstration ne dépend donc jamais du LLM.
- **Cache** : une note par (faits, modèle, version de la consigne), gardée dans `data/cache/notes/`. `python scripts/prepare_notes.py` pré-génère les notes des dossiers de démonstration en respectant le quota.
- **Ce que la note ne fait pas** : elle ne modifie ni le statut, ni l'action, ni les minutes imputables. L'interface affiche la décision du moteur, la note est un texte à côté, que le juriste relit.
- **Pourquoi** : dans le produit, la valeur du LLM est dans la **rédaction** (note au juriste, puis plus tard courrier à la compagnie), là où un humain passait du temps. La décision, elle, doit rester reproductible (D2). Les contrôles transforment « le LLM a sans doute raison » en « chaque phrase est rattachée à une preuve vérifiable, et le sens est vérifié ».
- **Pourquoi Mistral** : offre gratuite, hébergement dans l'UE (données de dossiers). Sur l'offre gratuite, `mistral-small` est fermé et `ministral-8b` limité à 2 requêtes par minute : en production, un modèle plus grand (`EC_NOTE_MODEL`) et une offre payante. Le client est une simple fonction `messages → texte` : changer de fournisseur ne touche ni aux contrôles ni aux tests.
- **Limite** : les contrôles attrapent les erreurs graves et mesurables (références, nombres, inversion du sens, lieux), pas toutes les nuances. Un petit modèle peut encore résumer maladroitement une preuve. C'est pourquoi la note reste destinée au juriste, jamais au passager. Suite : un jeu de notes relues par les juristes pour mesurer le taux d'erreur, puis un LLM juge évalué sur ce jeu.
- **Écarté** : laisser le LLM lire tout le JSON (bruit, coût, et risque qu'il « recalcule » la décision) ; afficher la note du LLM sans contrôle ; envoyer une note du LLM directement au passager.
