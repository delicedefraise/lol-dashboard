# Analyse ranked

Dashboard personnel de parties classées League of Legends (Caps75 et SPACFR, EUW).

- `index.html` : le dashboard (6 onglets, filtres, analyses). Icônes chargées depuis Data Dragon (CDN officiel Riot).
- `data.js` : les données (parties, rangs, catalogue). Généré par le script, ne pas éditer à la main.
- `config.json` : comptes suivis, région, début de saison.
- `scripts/fetch_riot.py` : récupère les nouvelles parties via l'API Riot et met à jour `data.js`.
- `scripts/fetch_meta.py` (+ `scripts/opgg_mcp.py`) : récupère la méta globale depuis le serveur MCP public d'OP.GG (tier list par lane, builds, runes, sorts, compétences, counters) et écrit `meta.js`. Aucune clé nécessaire.
- `meta.js` : la méta, chargée seulement à l'ouverture de l'onglet Méta. Données © OP.GG.
- `.github/workflows/maj-donnees.yml` : lance les deux scripts chaque jour et publie le résultat.

## Mettre à jour à la main

1. Mettre la clé dans `.env` : `RIOT_API_KEY=RGAPI-...` (ce fichier n'est jamais envoyé sur GitHub).
2. `python scripts/fetch_riot.py`
3. Contrôle sans rien écrire : `python scripts/fetch_riot.py --verifier 10`

## Mise à jour automatique

La clé est rangée dans les secrets du dépôt (`RIOT_API_KEY`). Pour la changer :

```
gh secret set RIOT_API_KEY
```

Le workflow tourne chaque matin ; onglet **Actions → Mise à jour des données → Run workflow** pour le lancer tout de suite.

Analyse ranked isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
