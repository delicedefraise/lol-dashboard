# Analyse ranked — contexte du projet pour Claude

Dashboard personnel League of Legends de deux joueurs : **Caps75#EUW** (le propriétaire du dépôt) et **SPACFR#EUW** (« Spac », son duo). Tout en français, tutoiement, ton direct.

- Site : https://delicedefraise.github.io/lol-dashboard/ (GitHub Pages, branche `main`, racine du dépôt)
- Dépôt : `delicedefraise/lol-dashboard` (public). Commits signés avec l'adresse noreply GitHub du compte.
- Saison suivie depuis le 2026-01-08 (voir `config.json`), files Solo/Duo et Flex.

## Architecture

| Fichier | Rôle |
|---|---|
| `index.html` | Tout le site (HTML + CSS + JS dans un seul fichier, pas de build). |
| `data.js` | `window.DATA` : parties (~70 champs par partie), rangs, catalogue. Généré, ne pas éditer à la main. |
| `meta.js` | `window.META` : méta OP.GG (tier list par lane, builds, runes, compétences, matchups complets). Chargé à la demande (onglet Méta). |
| `debriefs.js` | `window.DEBRIEFS` : debrief par partie (`analyse` chiffrée + `texte` du coach). Chargé à la demande (onglet Parties). |
| `scripts/fetch_riot.py` | API Riot → `data.js`. Bibliothèque standard uniquement. `--verifier N` recalcule N parties et compare. Complète les anciennes parties quand on ajoute des champs (`CHAMPS_AJOUTES`). |
| `scripts/fetch_meta.py` + `scripts/opgg_mcp.py` | Méta globale via le serveur MCP public d'OP.GG (`https://mcp-api.op.gg/mcp`, sans clé, réponses en format texte compact analysé par `opgg_mcp.analyser`). |
| `scripts/debrief.py` | Analyse chiffrée de la timeline Riot (impact des 10 joueurs, courbe d'or, morts avec zone, fenêtres de gank pour un jungler, objectifs). `--sans-ia` = analyse seule. Avec `ANTHROPIC_API_KEY` : texte du coach par l'API Claude. |
| `scripts/texte_debrief.py` | Avis du coach écrit par Claude Code lui-même (pas de clé API). Voir plus bas. |
| `compagnon/` + `compagnon.zip` | Compagnon de partie : programme Python à lancer sur le PC de jeu, lit l'API locale officielle Live Client Data (`https://127.0.0.1:2999`) et sert une page sur le Wi-Fi (port 8777) pour le téléphone : Mémo, Lanes (pistes de jeu), Items. `--demo` = partie fictive. Démo en ligne : `/compagnon/compagnon.html`. **Régénérer `compagnon.zip` après toute modification du dossier.** |
| `.github/workflows/maj-donnees.yml` | Tâche quotidienne (cron 05:00 UTC + bouton manuel) : parties Riot → debrief → méta → commit/push (se recale avec `git pull --rebase` avant de pousser). L'échec de la clé Riot n'empêche pas la méta ; il est signalé par un échec volontaire en fin de tâche. |
| `config.json` | Comptes suivis, région, début de saison. |

## Clés et secrets

- `.env` (jamais commité, dans `.gitignore`) : `RIOT_API_KEY=RGAPI-...` ; éventuellement `ANTHROPIC_API_KEY=` (le propriétaire **n'a pas** de clé Anthropic : les avis du coach sont écrits par Claude Code, voir plus bas).
- Secret GitHub `RIOT_API_KEY` : même clé. La clé de **dev** Riot expire toutes les 24 h → la tâche quotidienne échoue côté parties tant que le secret n'est pas renouvelé. Objectif : obtenir une **Personal API Key** (developer.riotgames.com, non expirante).
- Ne jamais demander qu'une clé soit collée dans le chat. Pour le secret GitHub : `gh secret set RIOT_API_KEY --repo delicedefraise/lol-dashboard` dans un terminal, l'utilisateur colle lui-même (clic droit / Ctrl+Maj+V dans le terminal de l'app).
- Avant chaque commit : vérifier qu'aucune clé n'est présente (`grep -E "RGAPI-[0-9a-f]{8}-|sk-ant-"`).

## Tâches courantes

- **Mettre à jour les parties** (clé dans `.env`) : `python scripts/fetch_riot.py`, puis commit + push de `data.js`.
- **Debrief après une session** (sans clé Anthropic) :
  1. `python scripts/debrief.py --sans-ia` (analyse des nouvelles parties, limitée à `--max`, défaut 12)
  2. `python scripts/texte_debrief.py a-rediger 6` : affiche les règles du coach, le format JSON et l'analyse des parties sans avis
  3. Claude Code écrit les avis (en respectant `SYSTEME` et `SCHEMA` de `debrief.py`) dans un fichier JSON `{match_id: {...}}` du scratchpad, puis `python scripts/texte_debrief.py ecrire FICHIER.json`
  4. Commit + push de `debriefs.js`
- **Méta** : `python scripts/fetch_meta.py` (~15-20 min, ~520 appels). Lancé aussi chaque jour par la tâche.
- **Tester le site** : `python -m http.server 8765` dans le dossier, aperçu en taille téléphone (375 px) **et** ordinateur. Vérifier les scripts avec `node --check` (extraire chaque `<script>` inline) : une apostrophe non échappée a déjà cassé une carte.
- Sur Windows, Python peut manquer de certificats racine : les scripts utilisent `certifi` s'il est installé. `python -I` ignore `PYTHONIOENCODING` : éviter les caractères spéciaux (✓) dans les `print`.

## Design (ne pas régresser)

- Style « bento + verre dépoli + touche LoL » : fond splash art du champion le plus joué (Data Dragon), cartes en verre, doré hextech `#c8aa6e`, turquoise victoire `#0ac8b9`, rouge défaite `#e84057`.
- Polices : **Instrument Serif** (titres, gros chiffres, rangs) + **Schibsted Grotesk** (texte). Pas de chiffres tabulaires (la virgule devient large dans Schibsted).
- Pas de surtitres en majuscules espacées. Navigation : onglets en haut sur ordinateur, barre flottante en bas sur mobile ; bouton **Méta** dans l'en-tête à côté du sélecteur de compte. Le logo ramène au Résumé.
- Spac utilise surtout le site **sur téléphone** : tout doit être lisible en 375 px, noms écrits en clair (pas seulement en info-bulle).
- Attention aux noms de classes CSS : `lx-b` est réservé au récap (colonne adversaire), les cartes bento sont `lx-bc`.
- Icônes : Data Dragon (champions, objets, sorts, runes) ; emblèmes de rang : Community Dragon.

## Règles Riot (important)

- Le compagnon n'utilise que l'API locale officielle (même info que la touche Tab). Jamais de lecture d'écran, de mémoire du jeu, d'alertes de pic de puissance, de timers d'ultimes ennemis, ni de conseil qui décide à la place du joueur. Les « pistes de jeu » sont des **options** avec leur raison.
- Refusé (triche) : outil qui lit la minimap/l'écran en direct, bot Discord qui analyse un partage d'écran pour conseiller en direct.
- Autorisé : analyse d'après-partie (debrief), scouting via l'API spectateur, builds/méta.
- Données OP.GG : toujours citées avec lien vers leur page.

## Idées en attente

- Scouting des 10 joueurs à l'écran de chargement (API spectateur, nécessite un relais type Cloudflare Worker pour garder la clé).
- Le compagnon n'a été testé qu'en mode démo : attendre les retours de Spac après de vraies parties (captures).
- Version Discord du debrief (`/debrief`) si besoin d'immédiateté.
