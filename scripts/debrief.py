"""Debrief d'après-partie : analyse chiffrée (timeline Riot) + texte de coach écrit par Claude.

Usage :
  python scripts/debrief.py              # debriefe les dernières parties qui n'en ont pas
  python scripts/debrief.py --max 5      # au plus 5 nouvelles parties (par défaut 12)
  python scripts/debrief.py --sans-ia    # seulement l'analyse chiffrée, sans appel à Claude

Clés lues dans l'environnement ou dans .env : RIOT_API_KEY (obligatoire), ANTHROPIC_API_KEY (pour le texte).
Écrit debriefs.js (window.DEBRIEFS), chargé par l'onglet Parties du site.
"""
import argparse
import datetime as dt
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_riot as F  # noqa: E402

RACINE = F.RACINE
SORTIE = os.path.join(RACINE, "debriefs.js")
PREFIXE = "window.DEBRIEFS = "
MODELE = "claude-opus-5-5"
ROLES = F.ROLES
DIAG = 14870  # la carte va de (0,0) base bleue à (~14870, ~14870) base rouge


# ---------------------------------------------------------------- géographie de la carte

def zone(pos):
    x, y = pos.get("x", 0), pos.get("y", 0)
    if x + y < 3800:
        return "base bleue"
    if x + y > 2 * DIAG - 3800:
        return "base rouge"
    if (x < 2600 and y > 5500) or (y > 12300 and x < 9500) or (x < 4600 and y > 10300):
        return "lane top"
    if (y < 2600 and x > 5500) or (x > 12300 and y < 9500) or (x > 10300 and y < 4600):
        return "lane bot"
    if abs(x - y) < 1500:
        return "lane mid"
    cote = "côté top" if y > x else "côté bot"
    if abs(x + y - DIAG) < 1400:
        return "rivière " + cote
    return ("jungle bleue " if x + y < DIAG else "jungle rouge ") + cote


def moitie_de(team_id, pos):
    """True si la position est dans la moitié de carte de l'équipe (bleue = 100)."""
    s = pos.get("x", 0) + pos.get("y", 0)
    return s < DIAG if team_id == 100 else s > DIAG


def dist(a, b):
    return math.hypot(a.get("x", 0) - b.get("x", 0), a.get("y", 0) - b.get("y", 0))


def lane_de(pos):
    z = zone(pos)
    for l in ("top", "mid", "bot"):
        if z == "lane " + l:
            return l
    return None


# ---------------------------------------------------------------- analyse d'une partie

def analyser(m, tl, puuid, dd):
    info = m["info"]
    P = info["participants"]
    par_id = {p["participantId"]: p for p in P}
    moi = next(p for p in P if p["puuid"] == puuid)
    equipe = moi["teamId"]
    frames = tl["info"]["frames"]
    evts = [e for f in frames for e in f.get("events", [])]
    duree = info["gameDuration"] / 60
    nom = lambda p: dd.champion(p["championName"])
    pos_role = lambda p: ROLES.get(p.get("teamPosition"), "?")
    vis_a_vis = {p["participantId"]: next((q for q in P if q["teamId"] != p["teamId"] and q.get("teamPosition") == p.get("teamPosition")), None) for p in P}

    def or_a(pid, minute):
        if len(frames) <= minute:
            return None
        return frames[minute]["participantFrames"][str(pid)]["totalGold"]

    # Note d'impact (0-100) : part des critères où le joueur fait mieux que son vis-à-vis
    def impact(p):
        q = vis_a_vis[p["participantId"]]
        if not q:
            return None
        kda = lambda x: (x["kills"] + x["assists"]) / max(1, x["deaths"])
        crit = [(kda(p), kda(q), 1.5), (q["deaths"], p["deaths"], 1.5), (p["kills"] + p["assists"], q["kills"] + q["assists"], 1),
                (p["goldEarned"], q["goldEarned"], 1), (p["totalDamageDealtToChampions"], q["totalDamageDealtToChampions"], 1),
                (p["visionScore"], q["visionScore"], 1 if p.get("teamPosition") != "UTILITY" else 2),
                ((p.get("challenges") or {}).get("killParticipation", 0), (q.get("challenges") or {}).get("killParticipation", 0), 1)]
        if p.get("teamPosition") != "UTILITY":
            crit.append((p["totalMinionsKilled"] + p["neutralMinionsKilled"], q["totalMinionsKilled"] + q["neutralMinionsKilled"], 1))
        o15p, o15q = or_a(p["participantId"], 15), or_a(q["participantId"], 15)
        if o15p is not None and o15q is not None:
            crit.append((o15p, o15q, 1.5))
        if p.get("teamPosition") in ("TOP", "JUNGLE"):
            crit.append((p.get("totalDamageTaken", 0) + p.get("damageSelfMitigated", 0), q.get("totalDamageTaken", 0) + q.get("damageSelfMitigated", 0), 0.75))
        t = sum((1 if a > b else 0.5 if a == b else 0) * w for a, b, w in crit)
        return round(100 * t / sum(w for *_, w in crit))

    joueurs = []
    for p in P:
        q = vis_a_vis[p["participantId"]]
        o10 = (or_a(p["participantId"], 10) - or_a(q["participantId"], 10)) if q and or_a(p["participantId"], 10) is not None else None
        o15 = (or_a(p["participantId"], 15) - or_a(q["participantId"], 15)) if q and or_a(p["participantId"], 15) is not None else None
        joueurs.append({
            "camp": "allié" if p["teamId"] == equipe else "ennemi", "moi": p["puuid"] == puuid,
            "champion": nom(p), "role": pos_role(p), "kda": "%d/%d/%d" % (p["kills"], p["deaths"], p["assists"]),
            "cs": p["totalMinionsKilled"] + p["neutralMinionsKilled"], "or": p["goldEarned"],
            "degats": p["totalDamageDealtToChampions"], "vision": p["visionScore"],
            "kp": round(100 * ((p.get("challenges") or {}).get("killParticipation") or 0)),
            "ecart_or_10": o10, "ecart_or_15": o15, "impact": impact(p),
            "objets": [x for x in (dd.objet_final(p.get("item%d" % i, 0)) for i in range(6)) if x],
        })

    # Écart d'or d'équipe toutes les 5 minutes
    def or_equipe(f, t):
        return sum(v["totalGold"] for k, v in f["participantFrames"].items() if par_id[int(k)]["teamId"] == t)
    courbe = [{"minute": i, "ecart": or_equipe(frames[i], equipe) - or_equipe(frames[i], 300 - equipe)} for i in range(0, len(frames), 5) if i > 0]
    ecarts = [(i, or_equipe(f, equipe) - or_equipe(f, 300 - equipe)) for i, f in enumerate(frames)]
    max_av = max(ecarts, key=lambda x: x[1]) if ecarts else (0, 0)
    max_re = min(ecarts, key=lambda x: x[1]) if ecarts else (0, 0)

    # Objectifs
    objectifs = []
    for e in evts:
        mn = round(e["timestamp"] / 60000, 1)
        if e["type"] == "ELITE_MONSTER_KILL":
            t = {"DRAGON": "dragon", "BARON_NASHOR": "Nashor", "RIFTHERALD": "Héraut", "HORDE": "larve", "ATAKHAN": "Atakhan"}.get(e.get("monsterType"), e.get("monsterType"))
            objectifs.append({"minute": mn, "objectif": t, "pour": "nous" if e.get("killerTeamId") == equipe else "eux"})
        elif e["type"] == "BUILDING_KILL":
            t = "tour " + {"TOP_LANE": "top", "MID_LANE": "mid", "BOT_LANE": "bot"}.get(e.get("laneType"), "?") if e.get("buildingType") == "TOWER_BUILDING" else "inhibiteur"
            objectifs.append({"minute": mn, "objectif": t, "pour": "eux" if e.get("teamId") == equipe else "nous"})

    # Mes morts : zone, nombre d'ennemis impliqués, alliés à proximité
    morts = []
    for e in evts:
        if e["type"] != "CHAMPION_KILL" or e.get("victimId") != moi["participantId"]:
            continue
        mn = e["timestamp"] / 60000
        f = frames[min(len(frames) - 1, int(round(mn)))]["participantFrames"]
        proches = sum(1 for p in P if p["teamId"] == equipe and p["participantId"] != moi["participantId"] and dist(f[str(p["participantId"])]["position"], e["position"]) < 2200)
        morts.append({"minute": round(mn, 1), "zone": zone(e["position"]), "tueur": nom(par_id[e["killerId"]]) if e.get("killerId") in par_id else "tour/sbires",
                      "ennemis_impliques": 1 + len(e.get("assistingParticipantIds") or []), "allies_proches": proches})

    # Fenêtres de gank (si jungler) : lane adverse avancée dans notre moitié pendant que leur jungler est de l'autre côté
    fenetres = []
    if moi.get("teamPosition") == "JUNGLE":
        jg_adv = next((p for p in P if p["teamId"] != equipe and p.get("teamPosition") == "JUNGLE"), None)
        for i in range(3, min(len(frames) - 1, 15)):
            f, f2 = frames[i]["participantFrames"], frames[i + 1]["participantFrames"]
            if not jg_adv:
                break
            pj = f[str(jg_adv["participantId"])]["position"]
            cote_jg = "top" if pj["y"] > pj["x"] else "bot"
            for lane, roles in (("top", ["TOP"]), ("bot", ["BOTTOM", "UTILITY"])):
                adv = [p for p in P if p["teamId"] != equipe and p.get("teamPosition") in roles]
                avances = [p for p in adv if lane_de(f[str(p["participantId"])]["position"]) == lane and moitie_de(equipe, f[str(p["participantId"])]["position"])]
                if avances and cote_jg != lane:
                    pris = lane_de(f2[str(moi["participantId"])]["position"]) == lane or lane_de(f[str(moi["participantId"])]["position"]) == lane
                    fenetres.append({"minute": i, "lane": lane, "jungler_adverse": "côté " + cote_jg, "pris": pris})
        # une fenêtre par lane et par tranche de 2 minutes suffit
        vues, dedup = set(), []
        for w in fenetres:
            k = (w["lane"], w["minute"] // 2)
            if k not in vues:
                vues.add(k)
                dedup.append(w)
        fenetres = dedup

    return {
        "match_id": m["metadata"]["matchId"], "date": F.heure_paris(info["gameStartTimestamp"]).strftime("%Y-%m-%d %H:%M"),
        "duree_min": round(duree, 1), "resultat": "victoire" if moi["win"] else "défaite",
        "abandon": bool(moi.get("gameEndedInSurrender")), "moi": {"champion": nom(moi), "role": pos_role(moi)},
        "joueurs": joueurs, "courbe_or_equipe": courbe,
        "plus_grande_avance": {"minute": max_av[0], "or": max_av[1]}, "plus_grand_retard": {"minute": max_re[0], "or": max_re[1]},
        "objectifs": objectifs, "mes_morts": morts, "fenetres_gank": fenetres,
    }


# ---------------------------------------------------------------- texte du coach (Claude)

SCHEMA = {
    "type": "object",
    "properties": {
        "responsabilite": {"type": "string", "enum": ["Défaite surtout de ton fait", "Défaite partagée", "Défaite surtout due à l'équipe",
                                                      "Victoire portée par toi", "Victoire d'équipe", "Victoire malgré une partie difficile"]},
        "titre": {"type": "string"},
        "resume": {"type": "string"},
        "equipe": {"type": "string"},
        "points_forts": {"type": "array", "items": {"type": "string"}},
        "a_ameliorer": {"type": "array", "items": {"type": "string"}},
        "moments_cles": {"type": "array", "items": {"type": "object", "properties": {"minute": {"type": "integer"}, "texte": {"type": "string"}},
                                                    "required": ["minute", "texte"], "additionalProperties": False}},
        "conseil": {"type": "string"},
    },
    "required": ["responsabilite", "titre", "resume", "equipe", "points_forts", "a_ameliorer", "moments_cles", "conseil"],
    "additionalProperties": False,
}

SYSTEME = """Tu es le coach League of Legends d'un joueur. Tu reçois l'analyse chiffrée d'une de ses parties classées (issue de l'API Riot : stats finales, écarts d'or minute par minute, objectifs, ses morts avec leur zone, et pour un jungler les fenêtres de gank détectées). Tu écris son debrief en français, en le tutoyant.

Règles :
- Appuie-toi uniquement sur les données fournies. Cite des minutes et des chiffres précis. N'invente aucun événement.
- Sois honnête dans les deux sens. Si la partie a été perdue à cause d'autres joueurs (une lane qui s'effondre, des objectifs lâchés en fin de partie), dis-le clairement en nommant les champions concernés. Si c'est lui qui a coûté la partie, dis-le aussi, sans le ménager ni l'accabler.
- Désigne toujours les autres joueurs par leur champion, jamais autrement.
- Même quand ce n'est pas sa faute, donne-lui ce qu'il pouvait faire de mieux de son côté : c'est le seul levier qu'il a.
- « impact » est une note sur 100 : la part des critères où le joueur fait mieux que son vis-à-vis direct (50 = à égalité).
- Les fenêtres de gank sont détectées à la minute près à partir des positions : présente-les comme des occasions probables, pas comme des certitudes.
- Ton : direct, concret, bienveillant, sans jargon inutile. Phrases courtes.

Format : titre = une ligne qui résume la partie ; resume = 2 à 3 phrases ; equipe = 1 à 2 phrases sur ce qu'ont fait les coéquipiers et l'adversaire ; points_forts et a_ameliorer = 1 à 3 éléments chacun ; moments_cles = 2 à 5 moments datés ; conseil = une phrase actionnable pour la prochaine partie."""


def ecrire_texte(client, analyse):
    rep = client.beta.messages.create(
        model=MODELE,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEME,
        messages=[{"role": "user", "content": "Analyse de la partie :\n" + json.dumps(analyse, ensure_ascii=False)}],
    )
    if rep.stop_reason == "refusal":
        return None
    texte = next((b.text for b in rep.content if b.type == "text"), None)
    return json.loads(texte) if texte else None


# ---------------------------------------------------------------- programme

def charger():
    if not os.path.exists(SORTIE):
        return {}
    t = open(SORTIE, encoding="utf-8").read().strip()
    return json.loads(t[len(PREFIXE):].rstrip(";"))


def lire_cle_claude():
    cle = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    env = os.path.join(RACINE, ".env")
    if not cle and os.path.exists(env):
        for ligne in open(env, encoding="utf-8"):
            if ligne.strip().startswith("ANTHROPIC_API_KEY="):
                cle = ligne.split("=", 1)[1].strip().strip('"').strip("'")
    return cle or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=12)
    ap.add_argument("--sans-ia", action="store_true")
    args = ap.parse_args()

    F.CONFIG = json.load(open(os.path.join(RACINE, "config.json"), encoding="utf-8"))
    api = F.Riot(F.lire_cle(), F.CONFIG["plateforme"], F.CONFIG["region"])
    dd = F.DataDragon()
    data = F.charger_data()
    deb = charger()

    client = None
    cle = None if args.sans_ia else lire_cle_claude()
    if cle:
        import anthropic  # pip install anthropic
        client = anthropic.Anthropic(api_key=cle)
    else:
        print("Pas de clé ANTHROPIC_API_KEY : analyse chiffrée seulement, sans texte de coach.")

    puuids = {c: api.compte(c)["puuid"] for c in F.CONFIG["comptes"]}
    # Les plus récentes d'abord ; on (re)traite celles sans debrief, ou sans texte si une clé Claude est disponible
    a_faire = [p for p in sorted(data["parties"], key=lambda r: r["debut"], reverse=True)
               if p["match_id"] not in deb or (client and not deb[p["match_id"]].get("texte"))][:args.max]
    print("%d partie(s) à debriefer" % len(a_faire))
    cache = {}
    for p in a_faire:
        mid = p["match_id"].rsplit("-", 1)[0]
        try:
            if mid not in cache:
                cache[mid] = (api.partie(mid), api.timeline(mid))
            m, tl = cache[mid]
            if not m or not tl:
                continue
            ana = deb.get(p["match_id"], {}).get("analyse") or analyser(m, tl, puuids[p["compte"]], dd)
            texte = None
            if client:
                try:
                    texte = ecrire_texte(client, ana)
                except Exception as e:  # une erreur d'API ne doit pas bloquer les autres parties
                    print("  texte non généré pour %s : %s" % (p["match_id"], str(e)[:150]))
            deb[p["match_id"]] = {"analyse": ana, "texte": texte, "genere": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ") if texte else None}
            print("  + %s %s %s%s" % (p["date"], p["champion"], p["resultat"], " (texte)" if texte else ""))
        except Exception as e:
            print("  échec %s : %s" % (p["match_id"], str(e)[:150]))

    with open(SORTIE, "w", encoding="utf-8", newline="\n") as f:
        f.write(PREFIXE + json.dumps(deb, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print("%d debriefs au total, %d appels Riot." % (len(deb), api.nb))


if __name__ == "__main__":
    main()
