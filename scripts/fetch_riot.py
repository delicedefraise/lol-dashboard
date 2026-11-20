"""Met à jour data.js à partir de l'API Riot.

Usage :
  python scripts/fetch_riot.py            # ajoute les nouvelles parties et rafraîchit les rangs
  python scripts/fetch_riot.py --verifier 5   # recalcule 5 parties déjà connues et compare (pas d'écriture)

La clé est lue dans la variable d'environnement RIOT_API_KEY, ou dans le fichier .env
à la racine du projet (ligne RIOT_API_KEY=...). Elle n'est jamais écrite ailleurs.
Aucune dépendance : bibliothèque standard Python uniquement.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
import ssl

try:  # certains Python Windows n'ont pas les certificats racine : on utilise certifi s'il est installé
    import certifi
    SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL = ssl.create_default_context()

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FICHIER_DATA = os.path.join(RACINE, "data.js")
PREFIXE = "window.DATA = "

ROLES = {"TOP": "Haut", "JUNGLE": "Jungle", "MIDDLE": "Milieu", "BOTTOM": "Bas", "UTILITY": "Support"}
TIERS_FR = {"IRON": "Fer", "BRONZE": "Bronze", "SILVER": "Argent", "GOLD": "Or", "PLATINUM": "Platine",
            "EMERALD": "Émeraude", "DIAMOND": "Diamant", "MASTER": "Maître", "GRANDMASTER": "Grand maître",
            "CHALLENGER": "Challenger"}
CLASSES = {"Fighter": "Combattant", "Mage": "Mage", "Assassin": "Assassin", "Marksman": "Tireur",
           "Support": "Support", "Tank": "Tank"}


# ---------------------------------------------------------------- utilitaires

def lire_cle():
    cle = os.environ.get("RIOT_API_KEY", "").strip()
    if not cle:
        env = os.path.join(RACINE, ".env")
        if os.path.exists(env):
            for ligne in open(env, encoding="utf-8"):
                if ligne.strip().startswith("RIOT_API_KEY="):
                    cle = ligne.split("=", 1)[1].strip().strip('"').strip("'")
    if not cle or cle.startswith("RGAPI-xxxx"):
        sys.exit("Clé API absente : mets-la dans .env (RIOT_API_KEY=RGAPI-...) ou dans la variable RIOT_API_KEY.")
    return cle


def heure_paris(ms):
    """Heure de Paris sans dépendre de la base de fuseaux (absente sous Windows)."""
    utc = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).replace(tzinfo=None)

    def dernier_dimanche(annee, mois):
        d = dt.datetime(annee, mois + 1, 1) - dt.timedelta(days=1) if mois < 12 else dt.datetime(annee, 12, 31)
        return d - dt.timedelta(days=(d.weekday() + 1) % 7)

    debut_ete = dernier_dimanche(utc.year, 3).replace(hour=1)
    fin_ete = dernier_dimanche(utc.year, 10).replace(hour=1)
    return utc + dt.timedelta(hours=2 if debut_ete <= utc < fin_ete else 1)


def s(v):
    return None if v is None else str(v)


def r3(x):
    return None if x is None else str(round(x, 3))


class Riot:
    def __init__(self, cle, plateforme, region):
        self.cle, self.plateforme, self.region = cle, plateforme, region
        self.appels = deque()
        self.nb = 0

    def _attendre(self):
        # Limites d'une clé dev/perso : 20 appels / s et 100 appels / 2 min.
        while True:
            maintenant = time.time()
            while self.appels and maintenant - self.appels[0] > 121:
                self.appels.popleft()
            recents = sum(1 for t in self.appels if maintenant - t < 1.05)
            if len(self.appels) < 95 and recents < 18:
                break
            time.sleep(0.5)
        self.appels.append(time.time())

    def get(self, hote, chemin, params=None):
        url = "https://%s.api.riotgames.com%s" % (hote, chemin)
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for essai in range(6):
            self._attendre()
            self.nb += 1
            req = urllib.request.Request(url, headers={"X-Riot-Token": self.cle, "User-Agent": "lol-dashboard"})
            try:
                with urllib.request.urlopen(req, timeout=30, context=SSL) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    sys.exit("Riot refuse la clé (HTTP %d) : elle est invalide ou expirée (une clé de dev dure 24 h)." % e.code)
                if e.code == 404:
                    return None
                if e.code == 429 or e.code >= 500:
                    attente = int(e.headers.get("Retry-After") or 5 * (essai + 1))
                    print("  HTTP %d, nouvelle tentative dans %d s" % (e.code, attente))
                    time.sleep(attente)
                    continue
                raise
            except urllib.error.URLError:
                time.sleep(5 * (essai + 1))
        raise RuntimeError("Échec répété sur " + chemin)

    def compte(self, riot_id):
        nom, tag = riot_id.split("#", 1)
        return self.get(self.region, "/riot/account/v1/accounts/by-riot-id/%s/%s" % (
            urllib.parse.quote(nom), urllib.parse.quote(tag)))

    def ids_parties(self, puuid, queue, depuis):
        ids, debut = [], 0
        while True:
            lot = self.get(self.region, "/lol/match/v5/matches/by-puuid/%s/ids" % puuid,
                           {"queue": queue, "startTime": depuis, "start": debut, "count": 100}) or []
            ids += lot
            if len(lot) < 100:
                return ids
            debut += 100

    def partie(self, mid):
        return self.get(self.region, "/lol/match/v5/matches/" + mid)

    def timeline(self, mid):
        return self.get(self.region, "/lol/match/v5/matches/%s/timeline" % mid)

    def ligues(self, puuid):
        return self.get(self.plateforme, "/lol/league/v4/entries/by-puuid/" + puuid) or []


def json_url(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "lol-dashboard"}), timeout=30, context=SSL) as r:
        return json.loads(r.read().decode("utf-8"))


class DataDragon:
    """Noms français des champions, objets, sorts et runes."""

    def __init__(self):
        base = "https://ddragon.leagueoflegends.com"
        v = json_url(base + "/api/versions.json")[0]
        cdn = "%s/cdn/%s/data/fr_FR/" % (base, v)
        champs = json_url(cdn + "champion.json")["data"]
        self.champ_nom = {c["id"]: c["name"] for c in champs.values()}
        self.champ_classe = {c["name"]: CLASSES.get((c.get("tags") or ["Fighter"])[0], "Combattant") for c in champs.values()}
        self.objets = json_url(cdn + "item.json")["data"]
        self.sorts = {int(x["key"]): x["name"] for x in json_url(cdn + "summoner.json")["data"].values()}
        self.runes = {}
        for arbre in json_url(cdn + "runesReforged.json"):
            for slot in arbre["slots"]:
                for rune in slot["runes"]:
                    self.runes[rune["id"]] = rune["name"]

    def champion(self, cid):
        return self.champ_nom.get(cid, cid)

    def objet_final(self, iid):
        """Garde les bottes améliorées et les objets terminés (pas les composants, balises, potions)."""
        o = self.objets.get(str(iid))
        if not o or iid == 0:
            return None
        tags = o.get("tags") or []
        if "Consumable" in tags or "Trinket" in tags:
            return None
        if "Boots" in tags:
            return o["name"] if iid != 1001 else None
        if o.get("into") or (o.get("gold") or {}).get("total", 0) < 2000:
            return None
        return o["name"]

    def categorie_objet(self, nom):
        for o in self.objets.values():
            if o["name"] == nom:
                tags = set(o.get("tags") or [])
                if "Boots" in tags:
                    return "Bottes"
                if "SpellDamage" in tags:
                    return "Magie"
                if tags & {"Damage", "AttackSpeed", "CriticalStrike", "ArmorPenetration", "LifeSteal"}:
                    return "Attaque"
                if tags & {"Health", "Armor", "SpellBlock"}:
                    return "Défense"
                return "Utilitaire"
        return "Utilitaire"


# ---------------------------------------------------------------- calcul d'une ligne

DUEL = {
    # cle: (champ du participant ou des challenges, source)
    "degats_subis": ("totalDamageTaken", "p"),
    "degats_mitiges": ("damageSelfMitigated", "p"),
    "soins_allies": ("totalHealsOnTeammates", "p"),
    "boucliers_allies": ("totalDamageShieldedOnTeammates", "p"),
    "cc": ("timeCCingOthers", "p"),
    "degats_batiments": ("damageDealtToBuildings", "p"),
    "tours_detruites": ("turretTakedowns", "p"),
    "wards": ("wardsPlaced", "p"),
    "wards_detruites": ("wardsKilled", "p"),
    "balises": ("detectorWardsPlaced", "p"),
    "temps_mort": ("totalTimeSpentDead", "p"),
    "plus_longue_serie": ("largestKillingSpree", "p"),
    "kp_adv_base": ("killParticipation", "c"),
    "part_degats_base": ("teamDamagePercentage", "c"),
    "part_subis": ("damageTakenOnTeamPercentage", "c"),
    "solo_kills_base": ("soloKills", "c"),
    "plaques_base": ("turretPlatesTaken", "c"),
    "esquives": ("skillshotsDodged", "c"),
    "skillshots": ("skillshotsHit", "c"),
    "cs_avance_max": ("maxCsAdvantageOnLaneOpponent", "c"),
    "niv_avance_max": ("maxLevelLeadLaneOpponent", "c"),
}


def duel_stats(moi, adv, ch, ach, duree):
    """Stats de duel pour toi (cle) et ton adversaire direct (adv_cle)."""
    out = {}
    for cle, (champ, src) in DUEL.items():
        v_moi = (moi if src == "p" else ch).get(champ)
        v_adv = (adv if src == "p" else ach).get(champ) if adv else None
        arrondi = (lambda x: None if x is None else str(round(x, 3))) if src == "c" else s
        nom = cle.replace("_base", "")
        if cle.endswith("_base"):  # déjà présent pour toi : on n'ajoute que l'adversaire
            out["adv_" + nom] = arrondi(v_adv)
        else:
            out[cle] = arrondi(v_moi)
            out["adv_" + cle] = arrondi(v_adv)
    out["adv_kp"] = out.pop("adv_kp_adv")
    out["adv_pinks"] = out["adv_balises"]
    return out


def riot_id(p):
    return "%s#%s" % (p.get("riotIdGameName") or p.get("summonerName"), p.get("riotIdTagline") or "")


def ligne_partie(compte, puuids_suivis, m, tl, dd, rangs_de):
    info = m["info"]
    parts = info["participants"]
    moi = next(p for p in parts if p["puuid"] == puuids_suivis[compte])
    pos = moi.get("teamPosition") or ""
    adv = next((p for p in parts if p["teamId"] != moi["teamId"] and p.get("teamPosition") == pos), None)
    equipe = [p for p in parts if p["teamId"] == moi["teamId"]]
    autres = [p for p in parts if p["teamId"] != moi["teamId"]]
    teams = {t["teamId"]: t for t in info["teams"]}
    obj, obj_adv = teams[moi["teamId"]]["objectives"], teams[adv["teamId"] if adv else (300 - moi["teamId"])]["objectives"]
    duree = info["gameDuration"] if info.get("gameEndTimestamp") else info["gameDuration"] / 1000
    debut = heure_paris(info["gameStartTimestamp"])

    frames = (tl or {}).get("info", {}).get("frames", [])

    def frame(minute, pid, champ):
        if len(frames) <= minute:
            return None
        return frames[minute]["participantFrames"][str(pid)].get(champ)

    def cs10(p):
        a, b = frame(10, p["participantId"], "minionsKilled"), frame(10, p["participantId"], "jungleMinionsKilled")
        return None if a is None else a + (b or 0)

    def ecart(minute, champ, a, b):
        x, y = frame(minute, a["participantId"], champ), frame(minute, b["participantId"], champ) if b else None
        return None if x is None or y is None else x - y

    def or_equipe(team_id):
        if len(frames) <= 15:
            return None
        return sum(frames[15]["participantFrames"][str(p["participantId"])]["totalGold"] for p in parts if p["teamId"] == team_id)

    oe, oa = or_equipe(moi["teamId"]), or_equipe(300 - moi["teamId"])
    kills_equipe = sum(p["kills"] for p in equipe)
    ch = moi.get("challenges") or {}
    kp = ch.get("killParticipation")
    if kp is None and kills_equipe:
        kp = (moi["kills"] + moi["assists"]) / kills_equipe

    partenaire = next((p for p in equipe if p["puuid"] in puuids_suivis.values() and p["puuid"] != moi["puuid"]), None)
    nom_part = next((c for c, pu in puuids_suivis.items() if partenaire and pu == partenaire["puuid"]), None)

    seuil = CONFIG["seuil_smurf_niveau"]

    def smurfs(liste):
        return [p for p in liste if (p.get("summonerLevel") or 999) <= seuil]

    details = []
    for p in smurfs(autres):
        rang, v, d, lp = "", "", "", ""
        entrees = rangs_de(p["puuid"])
        e = next((x for x in entrees if x["queueType"] == "RANKED_SOLO_5x5"), None) or \
            next((x for x in entrees if x["queueType"] == "RANKED_FLEX_SR"), None)
        if e:
            rang = "%s %s" % (e["tier"].capitalize(), e.get("rank", "")) if e["tier"] not in ("MASTER", "GRANDMASTER", "CHALLENGER") else e["tier"].capitalize()
            v, d, lp = e["wins"], e["losses"], e["leaguePoints"]
        details.append("~".join(map(str, [riot_id(p), dd.champion(p["championName"]), p["summonerLevel"],
                                          "%d/%d/%d" % (p["kills"], p["deaths"], p["assists"]),
                                          ROLES.get(p.get("teamPosition"), ""), rang.strip(), v, d, lp])))

    perks = (moi.get("perks") or {}).get("styles") or []
    rune = dd.runes.get(perks[0]["selections"][0]["perk"]) if perks else None
    sorts = " + ".join(sorted(filter(None, [dd.sorts.get(moi.get("summoner1Id")), dd.sorts.get(moi.get("summoner2Id"))])))
    objets = [dd.objet_final(moi.get("item%d" % i, 0)) for i in range(6)]
    or_total = sum(p["goldEarned"] for p in equipe)
    a = adv or {}
    ach = a.get("challenges") or {}

    return {
        "compte": compte,
        "match_id": "%s-%s" % (m["metadata"]["matchId"], compte.split("#")[0]),
        "date": debut.strftime("%Y-%m-%d"),
        "heure": str(debut.hour),
        "debut": debut.strftime("%Y-%m-%dT%H:%M"),
        "file": CONFIG["files"][str(info["queueId"])],
        "duree_min": str(round(duree / 60, 1)),
        "resultat": "V" if moi["win"] else "D",
        "side": "Bleu" if moi["teamId"] == 100 else "Rouge",
        "role": ROLES.get(pos, pos),
        "champion": dd.champion(moi["championName"]),
        "adv_champion": dd.champion(a["championName"]) if adv else None,
        "kills": s(moi["kills"]), "deaths": s(moi["deaths"]), "assists": s(moi["assists"]),
        "kp": r3(kp),
        "cs": s(moi["totalMinionsKilled"] + moi["neutralMinionsKilled"]),
        "cs_10": s(cs10(moi)),
        "gold": s(moi["goldEarned"]), "degats": s(moi["totalDamageDealtToChampions"]),
        "vision": s(moi["visionScore"]), "niveau": s(moi["champLevel"]),
        "ecart_or_15": s(ecart(15, "totalGold", moi, adv)),
        "ecart_niv_10": s(ecart(10, "level", moi, adv)),
        "adv_kills": s(a.get("kills")), "adv_deaths": s(a.get("deaths")), "adv_assists": s(a.get("assists")),
        "adv_cs": s(a["totalMinionsKilled"] + a["neutralMinionsKilled"]) if adv else None,
        "adv_cs_10": s(cs10(adv)) if adv else None,
        "adv_gold": s(a.get("goldEarned")), "adv_degats": s(a.get("totalDamageDealtToChampions")),
        "adv_vision": s(a.get("visionScore")), "adv_niveau": s(a.get("champLevel")),
        "premier_sang": "1" if obj["champion"]["first"] else "0",
        "premiere_tour": "1" if obj["tower"]["first"] else "0",
        "pinks": s(moi.get("detectorWardsPlaced", 0)),
        "abandon": "1" if moi.get("gameEndedInSurrender") else "0",
        "niveau_compte": s(moi.get("summonerLevel")),
        "adv_niveau_compte": s(a.get("summonerLevel")),
        "smurfs": str(len(details)),
        "smurfs_detail": "|".join(details) or None,
        "smurfs_allies": str(len(smurfs([p for p in equipe if p is not moi]))),
        "patch": ".".join(info["gameVersion"].split(".")[:2]),
        "rune": rune,
        "sorts": sorts,
        "part_degats": r3(ch.get("teamDamagePercentage")),
        "part_or": r3(moi["goldEarned"] / or_total) if or_total else None,
        "temps_mort_pct": r3(moi.get("totalTimeSpentDead", 0) / duree) if duree else None,
        "solo_kills": s(ch.get("soloKills", 0)),
        "plaques": s(ch.get("turretPlatesTaken", 0)),
        "multikill": s(moi.get("largestMultiKill", 0)),
        "premier_dragon": "1" if obj["dragon"]["first"] else "0",
        "dragons": s(obj["dragon"]["kills"]), "adv_dragons": s(obj_adv["dragon"]["kills"]),
        "barons": s(obj["baron"]["kills"]),
        "larves": s((obj.get("horde") or {}).get("kills", 0)),
        "heraut": "1" if (obj.get("riftHerald") or {}).get("kills", 0) else "0",
        "atakhan": s((obj.get("atakhan") or {}).get("kills", 0)),
        # Objectifs pris par l'équipe adverse
        "adv_barons": s(obj_adv["baron"]["kills"]),
        "adv_larves": s((obj_adv.get("horde") or {}).get("kills", 0)),
        "adv_heraut": "1" if (obj_adv.get("riftHerald") or {}).get("kills", 0) else "0",
        "adv_atakhan": s((obj_adv.get("atakhan") or {}).get("kills", 0)),
        # Jungle : toi et ton adversaire direct
        "camps": s(moi.get("neutralMinionsKilled", 0)), "adv_camps": s(a.get("neutralMinionsKilled")),
        "contre_jungle": s(ch.get("enemyJungleMonsterKills", 0)), "adv_contre_jungle": s(ach.get("enemyJungleMonsterKills")),
        "crabes": s(ch.get("scuttleCrabKills", 0)), "adv_crabes": s(ach.get("scuttleCrabKills")),
        "vols": s(ch.get("epicMonsterSteals", 0)), "adv_vols": s(ach.get("epicMonsterSteals")),
        "dragons_part": s(ch.get("dragonTakedowns", 0)), "adv_dragons_part": s(ach.get("dragonTakedowns")),
        "barons_part": s(ch.get("baronTakedowns", 0)), "adv_barons_part": s(ach.get("baronTakedowns")),
        # Combat, tank, soutien, vision, map : toi et ton adversaire direct
        **{cle: v for cle, v in duel_stats(moi, a, ch, ach, duree).items()},
        "ecart_or_equipe_15": s(oe - oa) if oe is not None and oa is not None else None,
        "ff": "1" if moi.get("gameEndedInSurrender") else "0",
        "partenaire": nom_part,
        "partenaire_champion": dd.champion(partenaire["championName"]) if partenaire else None,
        "partenaire_role": ROLES.get(partenaire.get("teamPosition")) if partenaire else None,
        "allies": "|".join(riot_id(p) for p in equipe if p is not moi),
        "adversaires": "|".join(riot_id(p) for p in autres),
        "objets": "|".join(o for o in objets if o),
    }


# ---------------------------------------------------------------- programme

def charger_data():
    if not os.path.exists(FICHIER_DATA):
        return {"parties": [], "rangs": [], "catalogue": {"champions": {}, "objets": {}}}
    texte = open(FICHIER_DATA, encoding="utf-8").read().strip()
    return json.loads(texte[len(PREFIXE):].rstrip(";"))


def ecrire_data(data):
    with open(FICHIER_DATA, "w", encoding="utf-8", newline="\n") as f:
        f.write(PREFIXE + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")


def main():
    global CONFIG
    ap = argparse.ArgumentParser()
    ap.add_argument("--verifier", type=int, default=0, help="recalcule N parties connues et compare, sans écrire")
    args = ap.parse_args()

    CONFIG = json.load(open(os.path.join(RACINE, "config.json"), encoding="utf-8"))
    api = Riot(lire_cle(), CONFIG["plateforme"], CONFIG["region"])
    dd = DataDragon()
    data = charger_data()

    puuids = {}
    for c in CONFIG["comptes"]:
        acc = api.compte(c)
        if not acc:
            sys.exit("Compte introuvable : " + c)
        puuids[c] = acc["puuid"]
    print("Comptes :", ", ".join(CONFIG["comptes"]))

    cache_rangs = {}

    def rangs_de(puuid):
        if puuid not in cache_rangs:
            cache_rangs[puuid] = api.ligues(puuid)
        return cache_rangs[puuid]

    cache_parties = {}

    def charger(mid):
        if mid not in cache_parties:
            cache_parties[mid] = (api.partie(mid), api.timeline(mid))
        return cache_parties[mid]

    if args.verifier:
        verifier(data, args.verifier, puuids, charger, dd, rangs_de, api)
        return

    # Complète les parties déjà connues avec les champs ajoutés depuis leur import
    a_completer = [p for p in data["parties"] if any(k not in p for k in CHAMPS_AJOUTES)]
    if a_completer:
        print("%d parties à compléter avec les nouveaux champs" % len(a_completer))
        parties_seules = {}
        for p in a_completer:
            mid = p["match_id"].rsplit("-", 1)[0]
            if mid not in parties_seules:
                parties_seules[mid] = cache_parties[mid][0] if mid in cache_parties else api.partie(mid)
            m = parties_seules[mid]
            if not m:
                continue
            ligne = ligne_partie(p["compte"], puuids, m, None, dd, lambda pu: [])
            for k in CHAMPS_AJOUTES:
                p[k] = ligne.get(k)

    connus = {p["match_id"] for p in data["parties"]}
    depuis = int(dt.datetime.fromisoformat(CONFIG["debut_saison"]).replace(tzinfo=dt.timezone.utc).timestamp())
    nouvelles = []
    for c, pu in puuids.items():
        court = c.split("#")[0]
        ids = []
        for q in CONFIG["files"]:
            ids += api.ids_parties(pu, int(q), depuis)
        ignorees = set(data.setdefault("ignorees", []))
        a_faire = [i for i in ids if "%s-%s" % (i, court) not in connus and i not in ignorees]
        print("%s : %d parties dans la saison, %d nouvelles" % (c, len(ids), len(a_faire)))
        for mid in a_faire:
            m, tl = charger(mid)
            if not m:
                continue
            moi = next(p for p in m["info"]["participants"] if p["puuid"] == pu)
            if m["info"]["gameDuration"] < 300 or not moi.get("teamPosition"):  # remake : on ne le retélécharge plus
                data["ignorees"].append(mid)
                continue
            nouvelles.append(ligne_partie(c, puuids, m, tl, dd, rangs_de))
            print("  +", nouvelles[-1]["date"], nouvelles[-1]["champion"], nouvelles[-1]["resultat"])

    data["parties"] = sorted(data["parties"] + nouvelles, key=lambda r: r["debut"])

    rangs = []
    for c, pu in puuids.items():
        for e in rangs_de(pu):
            file = {"RANKED_SOLO_5x5": "Solo/Duo", "RANKED_FLEX_SR": "Flex"}.get(e["queueType"])
            if file:
                rangs.append({"compte": c, "file": file, "tier": TIERS_FR.get(e["tier"], e["tier"]),
                              "division": e.get("rank", ""), "lp": str(e["leaguePoints"]),
                              "victoires": str(e["wins"]), "defaites": str(e["losses"])})
    if rangs:
        data["rangs"] = rangs

    cat = data.setdefault("catalogue", {"champions": {}, "objets": {}})
    for nom, classe in dd.champ_classe.items():
        cat["champions"].setdefault(nom, classe)
    for p in data["parties"]:
        for o in filter(None, (p.get("objets") or "").split("|")):
            if o not in cat["objets"]:
                cat["objets"][o] = dd.categorie_objet(o)

    data["maj"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    ecrire_data(data)
    print("%d nouvelles parties, %d au total, %d appels API." % (len(nouvelles), len(data["parties"]), api.nb))


def verifier(data, n, puuids, charger, dd, rangs_de, api):
    """Recalcule quelques parties déjà présentes et liste les champs qui diffèrent."""
    echantillon = data["parties"][-n:]
    ecarts = {}
    for ancien in echantillon:
        mid = ancien["match_id"].rsplit("-", 1)[0]
        m, tl = charger(mid)
        if not m:
            print("introuvable :", mid)
            continue
        nouveau = ligne_partie(ancien["compte"], puuids, m, tl, dd, rangs_de)
        for k, v in ancien.items():
            if k in ("smurfs_detail",):
                continue
            if str(v) != str(nouveau.get(k)):
                ecarts.setdefault(k, []).append((ancien["match_id"], v, nouveau.get(k)))
    print("%d parties comparées, %d appels API." % (len(echantillon), api.nb))
    if not ecarts:
        print("Aucun écart.")
    for k, lst in sorted(ecarts.items()):
        print("%-20s %d écart(s), ex. %s" % (k, len(lst), lst[:2]))


CONFIG = {}
CHAMPS_AJOUTES = ["adv_barons", "adv_larves", "adv_heraut", "adv_atakhan", "camps", "adv_camps",
                  "contre_jungle", "adv_contre_jungle", "crabes", "adv_crabes", "vols", "adv_vols",
                  "dragons_part", "adv_dragons_part", "barons_part", "adv_barons_part"]
CHAMPS_AJOUTES += sorted({k for k in duel_stats({}, {}, {}, {}, 1)})

if __name__ == "__main__":
    main()
