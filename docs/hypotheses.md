# Hypothèses et limites

Chaque hypothèse suit le même format :
**énoncé** → **pourquoi** → **risque si elle est fausse** → **comment la valider**.

Les hypothèses marquées ⚖️ doivent être validées avec un juriste.

---

## A. Hypothèses juridiques

### H1 — La CE porte sur le vol, et sa cause doit être identifiée ⚖️
- **Énoncé** : un « retard ATC » ou un « créneau retardé » ne suffit pas. Le module cherche la cause sous-jacente (météo, grève).
- **Pourquoi** : CJUE, C-108/26 (8 octobre 2026).
- **Risque** : faible, c'est la jurisprudence la plus récente.
- **Validation** : relecture juriste.

### H2 — La météo n'est une CE que si elle empêche le vol de se faire en sécurité ⚖️
- **Énoncé** : une météo « mauvaise » ne suffit pas. Il faut une météo **grave** : orage, visibilité très faible, vent fort ou rafales, neige ou précipitations verglaçantes.
- **Pourquoi** : c'est la condition retenue en pratique. La pluie ou un vent modéré sont des conditions ordinaires d'exploitation.
- **Risque** : il n'existe **aucun seuil légal chiffré**. Les seuils de `config/rules.yaml` sont des hypothèses.
- **Validation** : confronter les seuils à des décisions passées, avec les juristes.

### H3 — Le retard peut être en partie imputable à une CE ⚖️
- **Énoncé** : on estime les minutes imputables à la CE. Si `retard total − minutes imputables < 180 min`, la CE suffit à exonérer.
- **Pourquoi** : on déduit du retard total le temps imputable à l'événement extraordinaire.
- **Risque** : l'estimation est grossière (durée de l'épisode météo, pas le retard réel qu'il a causé).
- **Validation** : comparer aux justifications des compagnies sur des dossiers passés.

### H4 — Le régime juridique dépend de la date du vol
- **Énoncé** : vol avant le 23 octobre 2027 → règlement 261/2004 et jurisprudence. Après → règlement (UE) 2026/2202.
- **Pourquoi** : la plupart des nouvelles règles du 2026/2202 s'appliquent à partir du 23 octobre 2027.
- **Risque** : dispositions transitoires mal lues.
- **Validation** : lecture du texte au JOUE avec un juriste. Le prototype n'implémente que le régime actuel.

## B. Hypothèses sur les données

### H5 — Le dossier contient les aéroports et les horaires prévus et réels
- **Énoncé** : entrée minimale = numéro de vol, codes OACI (ou IATA) de départ et d'arrivée, heures prévues et réelles de départ et d'arrivée, en UTC.
- **Pourquoi** : c'est ce que donne le sujet, et ce qu'il faut pour mesurer le retard.
- **Risque** : heures réelles absentes, ou en heure locale.
- **Validation** : demander le format réel du flux.

### H6 — Les METAR suffisent pour caractériser la météo à l'aéroport
- **Énoncé** : les relevés METAR (vent, rafales, visibilité, phénomènes, plafond) au départ et à l'arrivée décrivent assez bien la météo locale.
- **Pourquoi** : source standard de l'aviation, historique gratuit (Iowa Environmental Mesonet), relevés environ toutes les 30 à 60 min.
- **Risque** : trous dans les relevés ; peu de contrôle qualité ; un phénomène bref entre deux relevés peut être manqué.
- **Validation** : contrôler 3 à 5 journées réelles connues (tempête, journée calme).

### H7 — La fenêtre de temps pertinente entoure les horaires du vol
- **Énoncé** : on regarde la météo au départ autour de l'heure prévue de départ, jusqu'au départ réel ; et à l'arrivée autour de l'heure prévue d'arrivée. Les marges sont dans `config/rules.yaml`.
- **Pourquoi** : une météo qui a disparu plusieurs heures avant le vol n'explique pas son retard.
- **Risque** : une perturbation du matin peut se propager toute la journée (effet domino sur les rotations).
- **Validation** : tester plusieurs largeurs de fenêtre sur les cas.

### H8 — Les grèves du contrôle aérien se sourcent à la main
- **Énoncé** : un calendrier `data/strikes.yaml`, avec pour chaque grève la date, la zone (pays, centres de contrôle) et une source.
- **Pourquoi** : pas d'API publique fiable.
- **Risque** : calendrier incomplet ; grève annoncée puis annulée ; liste des aéroports touchés incomplète ; survol non couvert.
- **Parade** : zones et périodes vérifiées déclarées (`coverage`) ; hors couverture, ou aéroport de la zone non cité, → `INCERTAIN` (D12).
- **Validation** : chaque entrée cite une source vérifiable (contrôlé au chargement et par les tests).
- **État** : couverture France (`LF`), juillet 2025 seulement, sur vérification manuelle.

### H9 — Une perturbation générale à un aéroport signale une cause extérieure
- **Énoncé** : beaucoup de vols retardés au même aéroport, dans la même plage horaire, **toutes compagnies confondues**, suggère une cause extérieure aux compagnies.
- **Pourquoi** : une panne ou un manque d'équipage touche une compagnie, pas tout l'aéroport.
- **Risque** : signal indirect ; il indique une cause commune, pas qu'elle soit extraordinaire.
- **Statut** : interface prévue, démontrée sur **données simulées**, marquées comme telles. En production, elle s'appuierait sur les flux de vols déjà reçus des agences.

## C. Hypothèses produit

### H10 — Les deux erreurs n'ont pas le même coût
- **Énoncé** :
  - dire `AUCUNE` à tort → un dossier part en automatique alors que la compagnie pourra s'exonérer : courrier inutile, image de l'agence abîmée, coût de procédure ;
  - dire `EC_PROBABLE` à tort → un dossier gagnable est mis en attente : manque à gagner.
- **Conséquence** : seuils asymétriques. Le statut `AUCUNE` exige les conditions les plus strictes (données complètes, aucun signal). Dans le doute → `INCERTAIN`.
- **Validation** : mesurer, sur les dossiers automatiques, la part de dossiers et le taux d'erreur.

### H11 — Pas de machine learning en v1
- **Énoncé** : décision par règles explicites.
- **Pourquoi** : pas de données annotées ; le droit exige une décision explicable et défendable.
- **Évolution** : avec un historique de dossiers et leur issue (payé, refusé, motif), on pourra calibrer les seuils, puis envisager un modèle **sous** les règles.

### H12 — Le LLM est hors de la décision
- **Énoncé** : en option, un LLM rédige l'explication pour le juriste, uniquement à partir des preuves JSON. Par défaut, un modèle de texte fixe. Implémenté dans `note.py`, avec contrôles des références et des nombres (D14).
- **Pourquoi** : une décision juridique doit être reproductible et auditée. « Le code décide, l'IA met en forme. »

## D. Limites assumées

| Limite | Conséquence | Suite possible |
|---|---|---|
| Motif de la compagnie inconnu | On détecte une CE plausible, pas prouvée | Lire le motif de refus (texte libre) au moment 3 |
| Météo en route | Non détectée (cas de C-108/26) | Données de régulation du trafic européen |
| Pas d'immatriculation | Vol précédent de l'avion non suivi (C-74/19) | Ajouter l'immatriculation au dossier |
| METAR incomplets | Faux `AUCUNE` possibles | Données manquantes → `INCERTAIN` |
| Seuils non légaux | Décision à valider | Calibrage avec les juristes |
| Minutes imputables approximatives | Exonération partielle mal estimée | Comparer aux dossiers passés |
| Pas de dossiers annotés | Pas d'évaluation statistique | Démonstration sur journées réelles vérifiées |
