# Comment fonctionne le Scraper de Nouvelles ATW - Expliqué Étape par Étape

## 📋 Vue d'ensemble
Le scraper de nouvelles (`scrapers/atw_news_scraper.py`) collecte les articles d'actualités sur **Attijariwafa Bank (ATW)** depuis 4 sources directes, les nettoie, les déduplique, les évalue et les sauvegarde dans un CSV.

> **Note 2026-04-15** : IR Attijariwafa et Attijari CIB ont été retirés — leurs pages d'articles n'exposent pas de date de publication (rendu côté client), ce qui laissait des lignes sans date. La colonne `snippet` a aussi été supprimée (toujours vide pour les scrapers directs ; `full_content` la remplace après enrichissement).

---

## 🚀 Les 13 Étapes - du Début à la Fin

### **ÉTAPE 1: Lancer le programme**
```bash
python scrapers/atw_news_scraper.py
```

**Qu'est-ce qui se passe?**
- Le programme lit les arguments de la ligne de commande
- Par défaut: pas de scrape Google News, pas de récupération de contenu complet
- Charge l'état précédent (articles déjà vus, dates de dernière mise à jour)

**Fichier impliqué:** `main()` (ligne 1285)

---

### **ÉTAPE 2: Charger les données existantes**

**Qu'est-ce qui se passe?**
- Le scraper charge le CSV existant (`data/historical/ATW_news.csv`) s'il existe
- Il crée un index par "URL canonique" pour chaque article
- Cela permet de détecter les doublons plus tard
- Les articles avec du contenu complet sont mémorisés pour ne pas être re-téléchargés

**Fichier impliqué:** `_load_existing_csv()` (ligne 1064)

**Pourquoi?** Pour éviter les doublons et réutiliser le contenu déjà collecté.

---

### **ÉTAPE 3: Récupérer les articles depuis 4 sources directes**

Le scraper interroge **4 sources de données** différentes pour trouver des articles sur ATW:

#### **Source 1: Medias24 - Page Thématique**
- Scrape la page HTML `medias24.com/sujet/attijariwafa-bank/`
- Extrait date, titre, URL
- **Résultat typique:** 6-12 articles

#### **Source 2: Medias24 - WordPress REST API**
- Interroge: `medias24.com/wp-json/wp/v2/posts?tags=8987`
- Tag ID 8987 = articles ATW sur Medias24
- JSON structuré avec date, titre, URL, excerpt
- Jusqu'à 300 articles (3 pages × 100)
- **Résultat typique:** 100-130 articles

#### **Source 3: Boursenews - Page Action**
- Scrape `boursenews.ma/action/attijariwafa-bank`
- La date n'est PAS sur la page de listing — elle est extraite de la page de l'article pendant l'étape d'enrichissement (JSON-LD, format français "Vendredi 10 Avril 2026")
- **Résultat typique:** 10-15 articles

#### **Source 4: MarketScreener - News ATW**
- Scrape `marketscreener.com/quote/stock/ATTIJARIWAFA-BANK-SA-41148801/news/`
- La date vient de l'attribut HTML `data-utc-date` sur `<span class="js-date-relative">` — ISO-8601 direct
- **Résultat typique:** 20-25 articles

#### **Source 5: L'Economiste - Recherche**
- Interroge: `leconomiste.com/?s=attijariwafa`
- La date vient de `<meta property="article:published_time">` sur la page de l'article (via `_extract_article_date`)
- **Résultat typique:** 5-10 articles

**Résultat de l'Étape 3:**
- ~150-250 articles bruts collectés (avec doublons, bruit, etc.)
- Chaque article contient: `date, titre, source, URL, résumé`

**Fichier impliqué:** La fonction `run()` (ligne 1195-1209) appelle chaque scraper

---

### **ÉTAPE 4: Filtrer le bruit (Noise Filter)**

**Qu'est-ce qui se passe?**

Le scraper examine CHAQUE article et supprime les "bruits":

#### **Filtre 1: Blocklist des domaines**
- ❌ Supprime si l'URL contient: `instagram.com`, `facebook.com`, `bebee.com`, `twitter.com`
- ❌ Supprime si c'est un site d'emploi: `indeed.com`, `linkedin.com`, `monster.com`
- ❌ Supprime si c'est une annuaire/Wikipedia: `wikipedia.org`, `xe.com`

#### **Filtre 2: BeBee job postings**
- ❌ Si source = BeBee ET le titre contient "job" ou "emploi" → SUPPRIMÉ

#### **Filtre 3: Instagram "Focus PME"**
- ❌ Si titre contient "Focus PME" (case-insensitive) → SUPPRIMÉ
- Raison: Ce ne sont pas des actualités ATW, c'est du contenu marketing

#### **Filtre 4: Couverture Égypte uniquement**
- ❌ Si article mentionne "Égypte" mais PAS "Maroc" → SUPPRIMÉ
- Raison: ATW est sur la Bourse de Casablanca (Maroc), pas d'activité en Égypte

**Fonction:** `filter_noise_articles()` (ligne 863)
**Appelée dans:** `_is_noise_article()` (ligne 457)

**Résultat de l'Étape 4:**
- ~120-200 articles (bruit enlevé)
- Les articles "vraiment irrélevants" supprimés

---

### **ÉTAPE 5: Dédupliquer les articles**

**Qu'est-ce qui se passe?**

Le scraper trouve et supprime les copies du même article:

#### **Stratégie 1: URL Canonique**
- Nettoie l'URL: enlève `www.`, normalise en minuscules
- Enlève les paramètres de suivi: `utm_*`, `fbclid`, `gclid`, etc.
- Résout les redirections Google News (exemple: `news.google.com/rss/articles/...` → URL vraie)
- Compare les URLs nettoyées
- Si deux articles ont la même URL nettoyée → DOUBLON, garde un seul

#### **Stratégie 2: (Date + Titre Normalisé)**
- Si l'URL canonique est identique, on ignore cette vérification
- Sinon, crée une clé: `DATE[:10] + "|" + TITRE_NORMALISÉ`
- Titre normalisé = enlève la source (ex: "- Medias24"), ponctuation, espaces
- Si deux articles ont la même clé → DOUBLON, garde un seul

#### **Stratégie 3: Google News Redirects**
- Google News utilise des URL de redirection
- Exemple: `news.google.com/rss/articles/xxx` redirigeant vers `medias24.com/article/yyy`
- Le scraper résout ces redirections et détecte si c'est un doublon
- Garde seulement la source directe (plus fiable)

#### **Classement des doublons:**
Quand il y a plusieurs copies du même article, garde celle-ci (par ordre):
1. ✅ **Sources directes** (Medias24, Boursenews) > Google News
2. ✅ **Articles avec contenu complet** > sans contenu
3. ✅ **Articles avec date** > sans date

**Fonction:** `deduplicate()` (ligne 821)

**Résultat de l'Étape 5:**
- ~100-160 articles uniques (doublons supprimés)
- Chaque article = une histoire différente

---

### **ÉTAPE 6: Fusionner avec les données existantes**

**Qu'est-ce qui se passe?**

Le scraper combine les nouveaux articles avec ceux du CSV précédent:

```python
merged: dict[str, dict] = dict(existing)  # Commence avec les anciens
for a in filtered:
    k = _url_key(a.get("url", ""))
    if k not in merged:
        merged[k] = a  # Ajoute le nouvel article
    else:
        # Article existant: garde le contenu ancien s'il est plus complet
        if existing[k].has_full_content and not a.has_full_content:
            a["full_content"] = existing[k]["full_content"]
```

**Pourquoi?** 
- Append-only: n'ajoute, jamais ne supprime les vieux articles
- Réutilise le contenu déjà récupéré (économise bande passante)

**Résultat de l'Étape 6:**
- ~200-350 articles au total (anciens + nouveaux)

---

### **ÉTAPE 7: Récupérer le contenu complet + date (optionnel)**

**Qu'est-ce qui se passe?**

Si vous lancez avec `--with-bodies` (ou `--deep` qui ajoute Google News):
```bash
python scrapers/atw_news_scraper.py --with-bodies
```

Pour CHAQUE article, le scraper:
1. Visite l'URL
2. Utilise `trafilatura` pour extraire le texte → `full_content`
3. Appelle `_extract_article_date(html)` pour récupérer la date de publication depuis la page :
   - `<meta property="article:published_time">` (L'Économiste)
   - JSON-LD `datePublished` (Boursenews, format français)
   - `<time datetime=...>` (fallback)
4. Si la ligne n'avait pas de date (cas Boursenews / L'Économiste), elle est back-fillée

**Temps par article:** ~1-2 secondes
**Pour 150 articles:** ~3-5 minutes

**Note:** Pas activé par défaut (trop lent). Le chemin rapide produit ~150 lignes en ~25s mais sans `full_content`.

**Fonction:** `enrich_with_bodies()` + `_fetch_article_body()` → `(body, date)` + `_fetch_article_date_only()` pour back-fill quand le body est déjà en cache

**Résultat de l'Étape 7:**
- Articles avec `full_content` rempli (texte complet)
- Peut être utilisé pour l'analyse de sentiment avancée

---

### **ÉTAPE 8: Appliquer les filtres et dédup APRÈS fusion**

**Qu'est-ce qui se passe?**

Après la fusion avec les anciennes données, on applique ENCORE:
1. Le filtre de bruit (certains articles anciens pourraient être bruyants)
2. La déduplication (nouvelle combinaison pourrait créer des doublons)

```python
final_rows = add_signal_metadata(
    deduplicate(
        filter_noise_articles(merged.values())
    )
)
```

**Pourquoi?** Pour garantir la qualité même si les anciennes données n'étaient pas nettoyées

**Résultat de l'Étape 8:**
- ~150-300 articles finaux de haute qualité

---

### **ÉTAPE 9: Calculer le score de signal (Signal Score)**

**Qu'est-ce qui se passe?**

Pour CHAQUE article, le scraper calcule deux colonnes:

#### **Colonne 1: `signal_score` (0-100)**

Score de pertinence = combien de "signal de trading" contient cet article

**Calcul:**
- Base: 10 points
- +20 si "ATW" ou "Attijariwafa" mentionné n'importe où
- +15 si mentionné dans le **titre** (très pertinent)
- +18 points par mot-clé financier dans le titre (max 3 = +54)
  - Mots-clés: "résultats", "earnings", "bénéfices", "dividendes", "stratégie", "fusion", "acquisition", "rating", "recommandation"
- +8 points par mot-clé financier dans le corps (max 4 = +32)
- +6 si source directe (pas Google News)
- -8 par "mention de passage" (max -24)
  - Mots: "forum", "salon", "sponsoring", "événement"
- -40 si couverture Égypte uniquement

**Résultat:** Nombre entre **0 et 100**

**Exemples:**
- "ATW posts record Q1 earnings, upgrades dividend" → **95-100** 🔥
- "ATW Q1 results show 10% growth" → **75-85** ✅
- "Casablanca Bourse gains 2%, ATW up" → **35-45** ⚠️
- Bruit → **0-10** 🚫

#### **Colonne 2: `is_atw_core` (0 ou 1)**

Drapeau: article est-il DIRECTEMENT sur ATW (1) ou seulement une mention (0)?

**Règle:**
- 1 = ATW mentionné ET (mot-clé financier dans le titre OU 2+ mots-clés dans le corps)
- 0 = sinon

**Exemples:**
- "ATW posts record earnings" → **1** (core)
- "Casablanca Bourse: ATW +2%, CIH +1%" → **0** (passing mention)

**Fonction:** `_compute_signal_fields()` (ligne 475)

**Résultat de l'Étape 9:**
- Chaque article a `signal_score` et `is_atw_core`

---

### **ÉTAPE 10: Ajouter la date de scrape**

**Qu'est-ce qui se passe?**

Le scraper ajoute `scraping_date` à chaque article:

```python
scraping_time = datetime.now(timezone.utc).isoformat()
# Exemple: "2026-04-15T17:42:54.515000+00:00"

for article in articles:
    # Si l'article existe déjà → GARDE l'ancienne date de scrape
    article.setdefault("scraping_date", scraping_time)
    # Si c'est un nouvel article → met la date du jour
```

**Pourquoi?** Tracer quand chaque article a été ajouté pour la première fois

**Colonne dans CSV:** `scraping_date` (ISO 8601)

**Résultat de l'Étape 10:**
- Chaque article horodaté

---

### **ÉTAPE 11: Trier par date (plus récent en premier)**

**Qu'est-ce qui se passe?**

```python
final_rows.sort(key=lambda r: r.get("date") or "", reverse=True)
```

Les articles sont arrangés:
- **Plus récent au-dessus** (date la plus grande)
- Les articles sans date vont en bas

**Résultat:** CSV lisible avec l'actualité la plus fraîche en premier

---

### **ÉTAPE 12: Sauvegarder le CSV**

**Qu'est-ce qui se passe?**

```python
save_csv(final_rows, out_path)
```

Le scraper écrit un fichier CSV avec les colonnes suivantes:

| Colonne | Signification | Exemple |
|---------|---------------|---------|
| `date` | Date de l'article (ISO) | `2026-04-15T14:30:00+00:00` |
| `ticker` | Code de l'action | `ATW` |
| `title` | Titre de l'article | `ATW posts record earnings` |
| `source` | Où l'article vient | `Medias24` |
| `url` | Lien vers article | `https://medias24.com/...` |
| `full_content` | Texte complet (si récupéré, une seule ligne) | `[HTML parsé en texte]` |
| `query_source` | Quel scraper l'a trouvé | `direct:medias24_wp` |
| `signal_score` | Score pertinence 0-100 | `78` |
| `is_atw_core` | C'est direct sur ATW? | `1` |
| `scraping_date` | Quand scrappé | `2026-04-15T17:42:54+00:00` |

> Les sauts de ligne sont aplatis par `_flatten()` à l'écriture — **une ligne CSV = un article**.

**Fichier créé:** `data/historical/ATW_news.csv`

**Résultat de l'Étape 12:**
- ✅ CSV mis à jour avec ~150-300 articles

---

### **ÉTAPE 13: Sauvegarder l'état (pour la prochaine exécution)**

**Qu'est-ce qui se passe?**

Le scraper enregistre son état dans un fichier JSON:

```json
{
  "seen_urls": {
    "medias24.com/article-xyz": "2026-04-15",
    "boursenews.com/atw-123": "2026-04-14"
  },
  "per_source_last_seen": {
    "direct:medias24_wp": "2026-04-15T17:42:54+00:00",
    "direct:boursenews_stock": "2026-04-15T16:30:00+00:00"
  },
  "failed_body_urls": [],
  "gnews_resolved": {},
  "last_full_run_ts": "2026-04-15T17:42:54+00:00"
}
```

**Fichier:** `data/scrapers/atw_news_state.json`

**Pourquoi?**
- La prochaine exécution peut sauter les articles déjà vus
- Permet une reprise si le script s'interrompt
- Optimise les futures exécutions (plus rapide)

**Résultat de l'Étape 13:**
- État persisté pour la prochaine utilisation

---

## 📊 Résumé du Processus (Vue d'ensemble)

```
ÉTAPE 1: Lancer le programme
    ↓
ÉTAPE 2: Charger les données existantes (CSV + état)
    ↓
ÉTAPE 3: Scraper 6 sources (150-250 articles bruts)
    ↓
ÉTAPE 4: Filtrer le bruit (BeBee, Instagram, Égypte) → 120-200 articles
    ↓
ÉTAPE 5: Dédupliquer (URL, date+titre) → 100-160 articles uniques
    ↓
ÉTAPE 6: Fusionner avec les anciennes données → 200-350 articles
    ↓
ÉTAPE 7: Récupérer contenu complet (optionnel) → articles enrichis
    ↓
ÉTAPE 8: Appliquer filtres + dedup ENCORE → 150-300 finaux
    ↓
ÉTAPE 9: Calculer signal_score + is_atw_core
    ↓
ÉTAPE 10: Ajouter scraping_date
    ↓
ÉTAPE 11: Trier par date (récent en premier)
    ↓
ÉTAPE 12: Sauvegarder CSV ✅
    ↓
ÉTAPE 13: Sauvegarder état JSON (pour prochaine run)
```

---

## 🔧 Commandes pratiques

### **Exécution rapide (par défaut, ~30 sec)**
```bash
python scrapers/atw_news_scraper.py
```
- Pas Google News
- Pas récupération de contenu
- Juste scrape + dédup + signal

### **Scrape profond (avec contenu + dates back-fill, ~3-5 min)**
```bash
python scrapers/atw_news_scraper.py --with-bodies
```
- Récupère le texte complet de chaque article
- Remplit les dates manquantes (Boursenews, L'Économiste)
- Utile pour analyse de sentiment avancée

### **Inclure Google News (lent, ~5-10 min)**
```bash
python scrapers/atw_news_scraper.py --deep
```
- Active Google News RSS
- Récupère les contenus complets
- Découverte la plus large (mais bruyante)

### **Nettoyer le CSV existant (reprocess)**
```bash
python scrapers/atw_news_scraper.py --backfill-existing
```
- Reprocess le CSV existant
- Réapplique filtres + dedup + signal
- Utile si vous changez les règles de filtrage

---

## 📝 Résultat Final

**Après toutes les 13 étapes, vous avez:**

✅ **CSV nettoyé** avec ~150-300 articles de haute qualité
✅ **Chaque article évalué** avec signal_score + is_atw_core
✅ **État sauvegardé** pour la prochaine exécution
✅ **Données prêtes** pour l'agent IA et l'analyse de sentiment

**Temps total:**
- Run rapide: ~30 secondes ⚡
- Run profond: ~3-5 minutes 🚀
- Run très profond (Google News): ~10-20 minutes 🌍

---

## 🎯 Exemple Concret

### **Avant scraping:**
- Zéro article

### **Après scraping (~25 sec, chemin rapide):**
```
Récupéré depuis:
- Medias24 WP:     126 articles
- Medias24 topic:   ~8 articles
- Boursenews:       11 articles
- MarketScreener:   24 articles
- L'Economiste:      5 articles
TOTAL BRUT: ~174 articles

Après bruit + dédup: 166 articles
Après fusion + filtres finaux: 166 articles ✅
100% avec date, 100% avec full_content (après --with-bodies)

Saved to: data/historical/ATW_news.csv
```

---

Voilà! C'est comment le scraper fonctionne du début à la fin. 🎯
