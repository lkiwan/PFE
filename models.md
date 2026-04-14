# Moteurs d'Évaluation : Fonctionnement et Cas d'Usage

Le système s'articule autour d'un script central, `recommendation_engine.py` (le moteur de recommandation). Ce script interroge l'ensemble des modèles de valorisation pour obtenir une estimation de la valeur intrinsèque d'une action, puis applique une pondération sectorielle pour formuler une décision finale.

Voici comment chaque modèle mathématique fonctionne et comment il est appliqué aux entreprises de la Bourse des Valeurs de Casablanca.

---

## 1. DDM (`ddm_model.py`) - Modèle d'Escompte des Dividendes
**Fonctionnement :** 
Ce modèle valorise une action en actualisant la somme de tous ses futurs dividendes vers leur valeur présente.
* **Formule principale :** `Dividende_Attendu / (Taux_de_Rendement_Requis - Taux_de_Croissance)`

**Application dans le projet :**
* Le moteur de recommandation attribue un **poids de 60%** au DDM pour le secteur bancaire et financier (ex: **ATW - Attijariwafa Bank** ou **BCP - Banque Centrale Populaire**). Les flux de trésorerie classiques (DCF) sont inutilisables pour les banques car la dette fait partie de leur matière première. Le versement de dividendes devient donc la seule mesure fiable de leur rentabilité.
* **Exemple d'exécution :** Si BCP paie un dividende qui croît régulièrement, le modèle peut estimer sa juste valeur à 650 MAD. Si le prix sur le marché est de 247 MAD, le DDM émet un signal d'ACHAT fort.

## 2. DCF (`dcf_model.py`) - Flux de Trésorerie Actualisés
**Fonctionnement :** 
Ce modèle projette le Free Cash Flow (FCF) de l'entreprise sur les 5 à 10 prochaines années, puis utilise le Coût Moyen Pondéré du Capital (WACC) pour actualiser cette valeur au présent, divisé par le nombre d'actions.

**Application dans le projet :**
* Pour les valeurs bancaires (ex: ATW), le moteur attribue un **poids de 0%** au modèle DCF. 
* En revanche, pour des industries manufacturières ou de télécommunications comme **IAM (Maroc Telecom)** ou **Mutandis**, le flux de trésorerie est la métrique absolue de création de valeur. Le moteur de recommandation y allouera un poids dominant (ex: 50%).

## 3. Modèle de Graham (`graham_model.py`) - Valeur Intrinsèque Défensive
**Fonctionnement :** 
Le script implémente une approche ultra-conservatrice issue de l'analyse fondamentale classique. Il intègre un système de secours (fail-safe) à deux niveaux :
1. **Formule de Croissance :** `Bénéfice_par_Action × (8.5 + 2 × Croissance) × 4.4 / Rendement_Obligataire`
2. **Nombre de Graham (Secours) :** `Racine_Carrée(22.5 × Bénéfice_par_Action × Valeur_Comptable_par_Action)`

**Application dans le projet :**
* Ce modèle agit comme un filtre d'évaluation rigide. Si le marché gonfle artificiellement le prix de l'action **ATW à 703 MAD**, mais que le modèle de Graham calcule que ses bénéfices actuels justifient au maximum **621 MAD**, le système pénalisera le score d'ATW, le classant comme surévalué technologiquement.

## 4. Valorisation Relative (`relative_valuation.py`) - Analyse des Multiples
**Fonctionnement :** 
Le modèle scanne l'entreprise et la compare à sa propre moyenne historique (sur 5 ans) à travers des ratios financiers clés comme le P/E (Price-to-Earnings Ratio) et le P/B (Price-to-Book Ratio).

**Application dans le projet :**
* Il permet d'identifier des opportunités de réversion à la moyenne ("mean-reversion"). Si **BCP** s'échange historiquement autour d'un P/E de 14x mais que la base de données actuelle le chiffre à 11x, le modèle de valorisation relative détecte une décote ("discount") temporaire du marché.

## 5. Simulation de Monte Carlo (`monte_carlo.py`) - Modélisation Stochastique
**Fonctionnement :** 
Le script exécute des milliers de trajectoires aléatoires sur le comportement futur de l'action en se basant sur sa volatilité historique (écart-type) selon le modèle du mouvement brownien géométrique.

**Application dans le projet :**
* Il ne donne pas un "prix juste", mais une **matrice de probabilité (Analyse de Risque)**. 
* **Exemple :** L'IA utilisera cette donnée pour affirmer : "Sur 10 000 simulations, la probabilité que BCP dépasse son prix actuel de 247 MAD durant l'année en cours est de 99.8%, représentant un investissement à très faible risque."

---

## 🟢 LA LOGIQUE DE DÉCISION DU SYSTÈME

Le cœur de décision de l'IA (intégré par `scoring_engine.py` et `recommendation_engine.py`) consolide ces données via la matrice suivante :

```python
# Pondération adaptative selon le secteur (Exemple pour une Banque) :
Prix_Intrinsèque_Final = (Valeur_DDM × 60%) + (Valeur_Graham × 20%) + (Valeur_Relative × 20%)

# Génération du signal en confrontant la Valeur Intrinsèque au Prix du Marché :
SI Prix_Intrinsèque_Final > Prix_Actuel_Bourse :
   ALORS Score = 100/100 → SIGNAL : BUY (Action sous-évaluée)

SI Prix_Intrinsèque_Final == Prix_Actuel_Bourse :
   ALORS Score = 50/100 → SIGNAL : HOLD (Action justement valorisée)

SI Prix_Intrinsèque_Final < Prix_Actuel_Bourse :
   ALORS Score = 0/100 → SIGNAL : SELL (Action surévaluée)
```

**Conclusion :** 
L'agent d'Intelligence Artificielle (Llama 3) va croiser le **Prix Intrinsèque Final** avec la matrice probabiliste de **Monte Carlo** pour émettre une consigne d'investissement claire (ex: Acheter BCP, Vendre ATW), reproduisant ainsi la rigueur d'analyse d'un gestionnaire de portefeuille institutionnel, le tout en quelques secondes pour les 80 composants de la place boursière.
