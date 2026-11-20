# ec-detector

Détection de **circonstances extraordinaires** (CE) au sens de l'article 5 §3 du règlement (CE) n° 261/2004, **par dossier**, à partir des **aéroports** et des **horaires du vol**.

## Guide de lecture

| Ce qui est demandé | Où le trouver |
|---|---|
| Choix techniques justifiés, code clair | [`docs/decisions.md`](docs/decisions.md) (D1 à D14), code dans `src/ec_detector/`, tests dans `tests/` |
| Prise de décision, choix et hypothèses | [`docs/hypotheses.md`](docs/hypotheses.md) (H1 à H12) et les sections 3 à 6 ci-dessous |
| Intégration au produit | [`docs/integration.md`](docs/integration.md) |
| Démonstration | `uvicorn ec_detector.api:app` (section 8) et `python scripts/evaluate.py` (section 7) |

---

## 1. Le problème

Un vol arrivé avec 3 h de retard ou plus, ou annulé, ouvre droit à une indemnité fixe : 250, 400 ou 600 € selon la distance.

La compagnie peut refuser de payer si elle **prouve** que le retard vient d'une circonstance extraordinaire, qui n'aurait pas pu être évitée même avec toutes les mesures raisonnables. La preuve est à sa charge.

Pour un réclamant, la question utile est donc :

> Pour ce dossier, une circonstance extraordinaire est-elle **plausible** ? Sur quelles **preuves** ? Combien de minutes de retard peut-elle **expliquer** ?

Répondre tôt et de façon fiable sert à :

- ne pas lancer un dossier perdu d'avance ;
- ne pas abandonner un dossier gagnable ;
- envoyer au juriste uniquement les cas qui méritent son temps.

## 2. Ce que fait le module

**Entrée** : un dossier (vol, aéroports de départ et d'arrivée, horaires prévus et réels).

**Sortie** : une décision JSON, traçable.

```json
{
  "case_id": "EXEMPLE-001",
  "status": "EC_PROBABLE",
  "ec_type": "METEO",
  "confidence": 0.85,
  "delay_total_minutes": 210,
  "delay_explained_minutes": 90,
  "evidence": [
    { "source": "METAR", "airport": "XXXX", "observed_at": "...", "raw": "...", "rule_id": "..." }
  ],
  "explanation": "…",
  "rules_version": "0.1.0",
  "legal_regime": "CE_261_2004",
  "computed_at": "..."
}
```

*(Exemple illustratif : valeurs fictives, pas un résultat réel.)*

Trois statuts, pensés pour l'automatisation :

| Statut | Signification | Action produit proposée |
|---|---|---|
| `AUCUNE` | Aucune CE détectée, avec forte confiance | Le dossier continue automatiquement |
| `EC_PROBABLE` | CE très probable, preuves à l'appui | Mise en attente ou abandon, preuves enregistrées |
| `INCERTAIN` | Signaux faibles, contradictoires ou données manquantes | Relecture par un juriste |

## 3. Principes de conception

1. **Le code décide, l'IA met en forme.** La décision vient de règles explicites. Un LLM peut, en option, rédiger l'explication pour le juriste, uniquement à partir des preuves JSON. Il ne décide jamais.
2. **Dans le doute, un humain.** Les seuils sont asymétriques : pour passer en `AUCUNE` (automatique), il faut des données complètes et nettes. Tout le reste va en `INCERTAIN`.
3. **Tout est traçable.** Chaque décision garde les données brutes, la règle appliquée, la version des règles et la date du calcul.
4. **Les règles dépendent de la date du vol.** Le régime juridique est choisi selon la date du vol (voir §5).
5. **Seuils en configuration, pas dans le code.** Ils sont dans `config/rules.yaml`, versionnés, et modifiables avec les juristes.

## 4. Périmètre

| Priorité | Signal | Source | État |
|---|---|---|---|
| 1 | Météo au départ et à l'arrivée | Relevés METAR historiques (Iowa Environmental Mesonet) | Fait |
| 2 | Grève du contrôle aérien | Calendrier `data/strikes.yaml`, sourcé à la main, avec zones et périodes couvertes | Fait (couverture : France, juillet 2025) |
| 3 | Perturbation générale de l'aéroport (beaucoup de vols retardés, toutes compagnies) | Interface prévue, démontrée sur **données simulées** | Prévu |

**Hors périmètre (documenté comme suite)** : collision aviaire, carburant sur la piste, passager violent, météo en route, vol précédent du même avion, motif déclaré par la compagnie.

**Pourquoi ce périmètre** : la météo est la CE la plus fréquemment invoquée, et la seule observable de façon objective à partir des seules données du sujet (aéroports + horaires). Mieux vaut un signal maîtrisé de bout en bout qu'une couverture large et fragile.

## 5. Cadre juridique pris en compte

- **Règlement (CE) n° 261/2004, art. 5 §3** : exonération en cas de CE inévitable. Charge de la preuve sur la compagnie.
- **CJUE, C-108/26, 8 octobre 2026** : une décision de gestion du trafic aérien (créneau retardé) n'est pas, à elle seule, une CE. Il faut remonter à sa cause. → Le module ne s'arrête pas au « retard ATC » : il cherche la cause (météo, grève).
- **CJUE, C-74/19** : une CE ayant touché un vol précédent du même avion peut exonérer s'il y a un lien direct. → Non couvert (pas d'immatriculation), documenté comme limite.
- **Minutes imputables** : un événement peut compter même s'il ne cause pas seul 3 h de retard. On déduit du retard total le temps qui lui est imputable. → Le module estime `delay_explained_minutes` ; si le retard restant passe sous 3 h, la CE suffit à exonérer.
- **Règlement (UE) 2026/2202** : réforme du 261/2004, avec une liste de CE. La plupart des nouvelles règles s'appliquent à partir du **23 octobre 2027**. → Le moteur choisit son jeu de règles selon la date du vol. Le prototype implémente le régime actuel.

## 6. Limites connues

Détail et justification dans [`docs/hypotheses.md`](docs/hypotheses.md).

- On détecte une CE **plausible**, pas une cause **prouvée** : on ne connaît pas le motif donné par la compagnie.
- La météo **en route** échappe au système.
- Pas d'immatriculation : pas de suivi du vol précédent de l'avion.
- Les METAR ont des trous et peu de contrôle qualité.
- Pas d'API publique pour les grèves : calendrier manuel, couverture limitée (France, juillet 2025). Hors couverture, le dossier va en `INCERTAIN`.
- Grèves imputées à la journée : les horaires précis des préavis ne sont pas sourcés.
- Les grèves ATC touchant le survol (vol qui traverse une zone en grève) ne sont pas détectées.
- Il n'existe pas de seuil légal chiffré de « météo grave » : les seuils sont des hypothèses à valider avec des juristes.
- Les minutes imputables sont une approximation.
- Pas de dossiers réels annotés : c'est une **démonstration**, pas une évaluation statistique.

## 7. Évaluation

```
python scripts/evaluate.py                  # tableau, matrice de confusion, indicateurs
python scripts/evaluate.py --json out.json  # détail complet en JSON
```

13 dossiers, journées réelles, vols fictifs (horaires selon une convention fixe, choisie avant de lancer le moteur). L'étiquette `expected.status` est une hypothèse de vérité, à confirmer par un juriste. Chaque dossier est **correct**, **renvoyé** à un juriste (`INCERTAIN` alors que la vérité est tranchée) ou **faux**.

| Indicateur | Résultat (règles 0.2.0, calendrier 2026-11-a) |
|---|---|
| Corrects | 11/13 |
| Renvoyés à un juriste | 2/13 (calendrier des grèves non vérifié à ces dates) |
| Faux | 0/13 |
| Traités sans humain | 8/13 |
| Erreurs parmi les automatiques | 0/8 |

Les dossiers incluent des pièges : pluie ordinaire, lendemain de tempête, tempête sur un autre aéroport, grève dans la zone mais aéroport non cité. **C'est une démonstration, pas une mesure** : 13 dossiers construits à la main ne disent rien du taux d'erreur réel. L'évaluation sur les retards Eurocontrol par aéroport et par cause (D4) n'est pas faite.

## 8. Interface de démonstration et API

```
pip install -e '.[api]'
uvicorn ec_detector.api:app --port 8000   # depuis la racine du repo
```

Puis ouvrir http://127.0.0.1:8000 :

- **Dossiers** : la file des dossiers de `cases/`, filtrée par action (continuer, mise en attente, relecture juriste). Pour chaque dossier : action, statut, minutes imputables, chronologie aux deux aéroports (période de retard, épisode météo, grève), raisons, preuves (METAR bruts, grèves sourcées) et le JSON stocké sur le dossier.
- **Nouveau dossier** : analyse d'un vol saisi à la main (heures en UTC).
- **Évaluation** : les mêmes indicateurs que `scripts/evaluate.py`.
- **Note pour le juriste** (dans le détail d'un dossier) : un LLM rédige une note à partir des seules raisons `R…` et preuves `E…`. Chaque paragraphe cite ses références, cliquables. Le code vérifie références et nombres, sinon modèle fixe (D14).

L'interface ne fait qu'afficher le JSON de l'API : toutes les décisions sont prises en Python. Endpoints : `POST /api/decide`, `POST /api/decide/batch`, `GET /api/cases`, `GET /api/evaluation`, `GET /api/meta`, `POST /api/note` ; documentation interactive sur `/docs`.

**Activer le LLM (optionnel)** : copier `.env.example` en `.env` (ignoré par git) et y mettre une clé Mistral (offre gratuite sur console.mistral.ai). Sans clé, tout fonctionne et la note vient du modèle fixe. L'offre gratuite étant limitée à 2 requêtes par minute, lancer `python scripts/prepare_notes.py` avant une présentation pour pré-générer les notes (environ 7 min).

Le cache METAR (`data/cache/`) n'est pas versionné : sur un clone neuf, le premier affichage télécharge les relevés (environ 30 s). Lancer `python scripts/evaluate.py` une fois avant une présentation pour remplir le cache.

## 9. Structure du repo (cible)

```
ec-detector/
  README.md
  docs/
    hypotheses.md     hypothèses et limites
    decisions.md      choix techniques et alternatives écartées
    integration.md    intégration dans le produit (backend TypeScript)
  config/rules.yaml   seuils et version des règles
  data/strikes.yaml   calendrier des grèves ATC, sourcé
  src/ec_detector/
    models.py         schémas d'entrée et de sortie
    weather.py        téléchargement, lecture et cache des METAR
    signals.py        signaux météo (relevé → règles déclenchées)
    strikes.py        calendrier des grèves ATC : couverture et correspondances
    engine.py         décision : règles → statut, confiance, preuves
    cli.py            ligne de commande
    evaluation.py     indicateurs d'évaluation (fonctions pures)
    note.py           note pour le juriste : LLM + contrôles, repli sur modèle fixe
    api.py            petite API FastAPI (+ interface static/)
  cases/              dossiers de test sur des journées réelles vérifiées
  scripts/evaluate.py
  scripts/prepare_notes.py   pré-génère les notes pour le juriste (quota LLM gratuit)
  tests/
```

## 10. Feuille de route

- [x] Étape 0 — Cadrage : problème, hypothèses, périmètre
- [x] Étape 1 — Données météo : téléchargement, lecture, cache, journées réelles vérifiées
- [x] Étape 2 — Règles et moteur de décision
- [x] Étape 3 — Grèves du contrôle aérien
- [x] Étape 4 — Tests et évaluation sur les cas
- [x] Étape 5 — API et documentation d'intégration

## 11. Perspectives : plus d'IA, surtout côté grèves

Le principe reste le même (D14) : **l'IA trouve et structure, le code vérifie, un humain valide ce qui entre dans les règles**. L'objectif est de lever la principale limite actuelle, un calendrier des grèves tenu à la main et à couverture étroite.

**Détection des grèves**

1. **Veille automatique des préavis.** Collecter en continu des sources publiques (communiqués DGAC et syndicats, presse, NOTAM, bulletins Eurocontrol), dans plusieurs pays et plusieurs langues. Un LLM transforme chaque article en événement structuré au format de `data/strikes.yaml` : zone, aéroports ou centres de contrôle cités, période avec heures et fuseau, statut (préavis, confirmée, levée), syndicats, source.
2. **Extraction vérifiable.** Chaque champ extrait doit être accompagné d'une citation exacte du texte source. Le code contrôle que la citation existe, que les dates sont cohérentes, que les codes OACI sont valides. Un événement non vérifié ne sert jamais à conclure `AUCUNE`.
3. **Validation humaine avant usage.** Les événements extraits arrivent dans une file de relecture ; une fois validés, ils sont versionnés dans le calendrier, comme aujourd'hui. On élargit la couverture (pays, périodes) sans perdre la traçabilité.
4. **Suivi du cycle de vie.** Rapprocher automatiquement préavis, confirmations et levées d'un même mouvement (une grève annoncée puis annulée n'est pas une CE).
5. **Qualification de la grève.** Classer la grève : contrôle aérien ou service extérieur à la compagnie (CE possible) ou personnel de la compagnie elle-même (en général pas une CE). Un mauvais classement change la décision, donc le cas douteux part en `INCERTAIN`.
6. **Confirmation par les données de trafic.** Un modèle de détection d'anomalies sur les séries de vols par aéroport (annulations et retards anormaux, toutes compagnies, données OpenSky ou Eurocontrol) confirme l'impact réel d'une grève, ou signale une perturbation absente du calendrier, qui part en relecture.
7. **Grèves de survol.** Croiser la trajectoire du vol (OpenSky) avec les centres de contrôle en grève, pour couvrir les vols qui traversent une zone touchée sans y atterrir.

**Autres pistes**

- **Motif déclaré par la compagnie** : un LLM extrait le motif invoqué dans la réponse de la compagnie ; le code le confronte aux preuves (météo, grève) et signale les contradictions au juriste.
- **Calibration sur dossiers réels** : une fois des dossiers annotés par les juristes disponibles, ajuster seuils et confiance par apprentissage, et donner la priorité en relecture aux `INCERTAIN` les plus informatifs (apprentissage actif).
- **Note pour le juriste enrichie** : retrouver la jurisprudence pertinente (recherche dans un corpus d'arrêts CJUE et nationaux) et la citer, avec les mêmes contrôles de références que les preuves.
