"""Scouting du jungler adverse : ses habitudes d'après ses dernières parties en jungle.

Usage :
  python scripts/scouting.py --compte "Caps75#EUW"           # attend que la partie démarre (API spectateur), puis analyse
  python scripts/scouting.py --test "SPACFR#EUW" --champion Zac   # analyse directe d'un joueur, sans partie en cours

Écrit scouting.json (résultat affiché par le site) et met à jour scouting_cache.json (parties déjà analysées).
Bibliothèque standard uniquement ; clé RIOT_API_KEY (environnement ou .env).
"""
import argparse
import collections
import datetime as dt
import json
import os
import statistics
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch_riot as F  # noqa: E402
from debrief import zone, moitie_de, lane_de  # noqa: E402

RACINE = F.RACINE
SORTIE = os.path.join(RACINE, "scouting.json")
CACHE = os.path.join(RACINE, "scouting_cache.json")
CHATIMENT = 11
NB_PARTIES = 20
MAX_PARTIES_LUES = 40


def attendre_partie(api, puuid, minutes):
    fin = time.time() + minutes * 60
    while True:
        g = api.get(api.plateforme, "/lol/spectator/v5/active-games/by-summoner/" + puuid)
        if g:
            return g
        if time.time() > fin:
            return None
        print("  partie pas encore commencée, nouvel essai dans 15 s")
        time.sleep(15)


def resume_partie(m, tl, puuid):
    """Habitudes d'un jungler sur une partie (None si ce n'était pas une partie en jungle)."""
    info = m["info"]
    p = next((x for x in info["participants"] if x["puuid"] == puuid), None)
    if not p or p.get("teamPosition") != "JUNGLE" or info["gameDuration"] < 600:
        return None
    pid, eq = str(p["participantId"]), p["teamId"]
    frames = tl["info"]["frames"]
    pos = lambda i: frames[i]["participantFrames"][pid]["position"] if i < len(frames) else {"x": 0, "y": 0}
    # Départ : position à 1:00 (devant son premier camp)
    d = pos(1)
    cote = "top" if d["y"] > d["x"] else "bot"
    buff = ("bleu" if cote == "top" else "rouge") if eq == 100 else ("rouge" if cote == "top" else "bleu")
    # Présence en lane (minutes 2 à 10) : première apparition et lanes visitées
    premiere, visites = None, collections.Counter()
    for i in range(2, min(11, len(frames))):
        l = lane_de(pos(i))
        if l:
            visites[l] += 1
            if not premiere and i <= 8:
                premiere = (l, i)
    # Invade : présence dans la jungle adverse avant 4 min, et minutes passées chez l'adversaire avant 10 min
    chez_eux = [i for i in range(1, min(11, len(frames))) if not moitie_de(eq, pos(i)) and zone(pos(i)).startswith("jungle")]
    # Premier retour en base (après 3 min)
    retour = next((i for i in range(3, min(15, len(frames))) if zone(pos(i)).startswith("base")), None)
    evts = [e for f in frames for e in f.get("events", [])]
    ka10 = sum(1 for e in evts if e["type"] == "CHAMPION_KILL" and e["timestamp"] < 600000
               and (e.get("killerId") == p["participantId"] or p["participantId"] in (e.get("assistingParticipantIds") or [])))
    premier_kill = next((e for e in evts if e["type"] == "CHAMPION_KILL" and e["timestamp"] < 480000
                         and (e.get("killerId") == p["participantId"] or p["participantId"] in (e.get("assistingParticipantIds") or []))), None)
    obj = next((e for e in evts if e["type"] == "ELITE_MONSTER_KILL" and e.get("killerTeamId") == eq
                and e.get("monsterType") in ("DRAGON", "HORDE", "RIFTHERALD")), None)
    ch = p.get("challenges") or {}
    return {
        "champion": p["championName"], "victoire": p["win"], "date": info["gameStartTimestamp"],
        "depart_cote": cote, "depart_buff": buff,
        "premiere_lane": premiere[0] if premiere else None, "premiere_lane_min": premiere[1] if premiere else None,
        "premier_kill_lane": (lane_de(premier_kill["position"]) or "jungle") if premier_kill else None,
        "premier_kill_min": round(premier_kill["timestamp"] / 60000, 1) if premier_kill else None,
        "visites": dict(visites), "invade_tot": any(i <= 4 for i in chez_eux), "minutes_chez_eux": len(chez_eux),
        "retour_min": retour, "ka_avant_10": ka10,
        "camps_10": frames[10]["participantFrames"][pid].get("jungleMinionsKilled") if len(frames) > 10 else None,
        "crabes": ch.get("scuttleCrabKills", 0), "contre_jungle": ch.get("enemyJungleMonsterKills", 0),
        "premier_objectif": {"DRAGON": "dragon", "HORDE": "larves", "RIFTHERALD": "Héraut"}.get(obj.get("monsterType")) if obj else None,
        "premier_objectif_min": round(obj["timestamp"] / 60000, 1) if obj else None,
    }


def agreger(parties):
    n = len(parties)
    if not n:
        return None
    compte = lambda cle: collections.Counter(x[cle] for x in parties if x.get(cle))
    def mode(cle):
        c = compte(cle)
        if not c:
            return None
        v, k = c.most_common(1)[0]
        return {"valeur": v, "fois": k, "sur": n}
    med = lambda l: round(statistics.median(l), 1) if l else None
    moy = lambda l: round(sum(l) / len(l), 1) if l else None
    lane = mode("premiere_lane")
    visites = collections.Counter()
    for x in parties:
        visites.update(x.get("visites") or {})
    obj = mode("premier_objectif")
    return {
        "parties": n,
        "depart": mode("depart_cote"), "buff": mode("depart_buff"),
        "premier_gank": lane, "premier_gank_min": med([x["premiere_lane_min"] for x in parties if lane and x.get("premiere_lane") == lane["valeur"] and x.get("premiere_lane_min")]),
        "lanes_gankees": [l for l, _ in visites.most_common()],
        "invade_tot": {"fois": sum(1 for x in parties if x["invade_tot"]), "sur": n},
        "minutes_chez_eux": moy([x["minutes_chez_eux"] for x in parties]),
        "premier_retour": med([x["retour_min"] for x in parties if x.get("retour_min")]),
        "premier_objectif": obj, "premier_objectif_min": med([x["premier_objectif_min"] for x in parties if obj and x.get("premier_objectif") == obj["valeur"] and x.get("premier_objectif_min")]),
        "crabes": moy([x["crabes"] for x in parties]), "contre_jungle": moy([x["contre_jungle"] for x in parties]),
        "ka_avant_10": moy([x["ka_avant_10"] for x in parties]), "camps_10": moy([x["camps_10"] for x in parties if x.get("camps_10") is not None]),
        "winrate": round(100 * sum(1 for x in parties if x["victoire"]) / n),
    }


def analyser_jungler(api, dd, puuid, champion_actuel, cache):
    deja = cache.setdefault(puuid, {})
    ids = []
    for q in (420, 440):
        ids += api.get(api.region, "/lol/match/v5/matches/by-puuid/%s/ids" % puuid, {"queue": q, "count": 30}) or []
    ids = sorted(set(ids), reverse=True)  # les identifiants croissent avec le temps : plus récents d'abord
    lues = 0
    for mid in ids:
        if sum(1 for v in deja.values() if v) >= NB_PARTIES or lues >= MAX_PARTIES_LUES:
            break
        if mid in deja:
            continue
        m = api.partie(mid)
        lues += 1
        if not m:
            continue
        p = next((x for x in m["info"]["participants"] if x["puuid"] == puuid), None)
        if not p or p.get("teamPosition") != "JUNGLE":
            deja[mid] = None  # pas une partie en jungle : on s'en souvient pour ne pas la relire
            continue
        tl = api.timeline(mid)
        deja[mid] = resume_partie(m, tl, puuid) if tl else None
    parties = sorted([v for v in deja.values() if v], key=lambda x: x["date"], reverse=True)[:NB_PARTIES]
    sur_champ = [x for x in parties if x["champion"] == champion_actuel]
    champs = collections.Counter(x["champion"] for x in parties)
    pool = [{"champion": dd.champion(c), "parties": k, "winrate": round(100 * sum(1 for x in parties if x["champion"] == c and x["victoire"]) / k)} for c, k in champs.most_common(4)]
    serie, res = 0, None
    for x in parties:
        if res is None:
            res = x["victoire"]
        if x["victoire"] != res:
            break
        serie += 1
    return {
        "sur_champion": agreger(sur_champ) if len(sur_champ) >= 4 else None,
        "parties_sur_champion": len(sur_champ),
        "general": agreger(parties), "pool": pool,
        "serie": {"victoires": bool(res), "nombre": serie} if parties else None,
    }


def rang(api, puuid):
    for e in api.ligues(puuid):
        if e["queueType"] == "RANKED_SOLO_5x5":
            v, d = e["wins"], e["losses"]
            return {"tier": F.TIERS_FR.get(e["tier"], e["tier"]), "division": e.get("rank", ""), "lp": e["leaguePoints"],
                    "winrate": round(100 * v / max(1, v + d)), "parties": v + d}
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compte", default="Caps75#EUW")
    ap.add_argument("--attente", type=float, default=8, help="minutes d'attente maximum que la partie démarre")
    ap.add_argument("--test", help="Riot ID à analyser directement (sans partie en cours)")
    ap.add_argument("--champion", help="avec --test : champion à considérer comme joué")
    a = ap.parse_args()

    F.CONFIG = json.load(open(os.path.join(RACINE, "config.json"), encoding="utf-8"))
    api = F.Riot(F.lire_cle(), F.CONFIG["plateforme"], F.CONFIG["region"])
    dd = F.DataDragon()
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    nom_par_cle = {int(c["key"]): cid for cid, c in F.json_url("https://ddragon.leagueoflegends.com/cdn/%s/data/fr_FR/champion.json" % F.json_url("https://ddragon.leagueoflegends.com/api/versions.json")[0])["data"].items()}

    if a.test:
        acc = api.compte(a.test)
        puuid, champ, partie = acc["puuid"], a.champion, None
        print("Mode test :", a.test)
    else:
        moi = api.compte(a.compte)
        print("Attente de la partie de", a.compte)
        g = attendre_partie(api, moi["puuid"], a.attente)
        if not g:
            json.dump({"maj": dt.datetime.now(dt.timezone.utc).isoformat(), "statut": "pas de partie", "compte": a.compte}, open(SORTIE, "w", encoding="utf-8"), ensure_ascii=False)
            sys.exit("Aucune partie en cours trouvée pour %s." % a.compte)
        mon_equipe = next(p["teamId"] for p in g["participants"] if p["puuid"] == moi["puuid"])
        adv = [p for p in g["participants"] if p["teamId"] != mon_equipe]
        jg = next((p for p in adv if CHATIMENT in (p.get("spell1Id"), p.get("spell2Id"))), None)
        if not jg:
            json.dump({"maj": dt.datetime.now(dt.timezone.utc).isoformat(), "statut": "pas de jungler", "compte": a.compte}, open(SORTIE, "w", encoding="utf-8"), ensure_ascii=False)
            sys.exit("Pas de Châtiment en face : pas de jungler à analyser.")
        puuid, champ = jg["puuid"], nom_par_cle.get(jg["championId"])
        partie = {"id": g.get("gameId"), "debut": g.get("gameStartTime"), "file": g.get("gameQueueConfigId")}
        print("Jungler adverse :", champ)

    res = analyser_jungler(api, dd, puuid, champ, cache)
    sortie = {"maj": dt.datetime.now(dt.timezone.utc).isoformat(), "statut": "ok", "compte": a.compte if not a.test else a.test,
              "partie": partie, "champion": dd.champion(champ) if champ else None, "cle_champion": champ, "rang": rang(api, puuid), **res}
    json.dump(sortie, open(SORTIE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(cache, open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    g = res["general"]
    print("Analyse : %d parties en jungle (%d sur %s), %d appels." % (g["parties"] if g else 0, res["parties_sur_champion"], champ, api.nb))


if __name__ == "__main__":
    main()
