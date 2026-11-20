"""Récupère la méta globale (toutes divisions, ranked solo) depuis le serveur MCP d'OP.GG
et l'écrit dans meta.js : tier list par lane, puis pour chaque champion et chaque lane
où il est joué : build, bottes, objets de départ, runes, sorts, ordre des compétences, counters.

Usage : python scripts/fetch_meta.py
Aucune clé nécessaire. Données © OP.GG, affichées avec mention et lien vers leur site.
"""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from opgg_mcp import OpggMCP  # noqa: E402

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SORTIE = os.path.join(RACINE, "meta.js")
POSITIONS = ["top", "jungle", "mid", "adc", "support"]
ROLE_RATE_MIN = 0.05  # on ignore les lanes où le champion est très rarement joué

LISTE = ["{champion,tier,rank,rank_prev,win_rate,pick_rate,ban_rate,play,role_rate,kda}"]
ITEMS = "{ids[],ids_names[],pick_rate,play,win}"
ANALYSE = [
    "data.summary.average_stats.{play,win_rate,pick_rate,ban_rate,tier,rank}",
    "data.starter_items." + ITEMS,
    "data.core_items." + ITEMS,
    "data.boots." + ITEMS,
    "data.fourth_items[]." + ITEMS,
    "data.fifth_items[]." + ITEMS,
    "data.sixth_items[]." + ITEMS,
    "data.runes.{primary_page_id,primary_page_name,primary_rune_ids[],primary_rune_names[],secondary_page_id,"
    "secondary_page_name,secondary_rune_ids[],secondary_rune_names[],stat_mod_ids[],stat_mod_names[],pick_rate,play,win}",
    "data.summoner_spells.{ids[],ids_names[],pick_rate,play,win}",
    "data.skills.{order[],pick_rate,play,win}",
    "data.skill_masteries.{ids[],pick_rate,play,win}",
    "data.strong_counters[].{champion_id,champion_name,my_win_rate,play}",
    "data.weak_counters[].{champion_id,champion_name,my_win_rate,play}",
]


def cle_opgg(cle):
    """Identifiant Data Dragon (MasterYi) -> format OP.GG (MASTER_YI)."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", cle).upper()


def nom_matchup(nom):
    """Nom affiché (anglais) -> format de l'outil de matchup (Lee Sin -> LEE_SIN, K'Sante -> KSANTE)."""
    return re.sub(r"_+", "_", re.sub(r"[^A-Z0-9 ]", "", nom.upper().replace("&", " ")).strip().replace(" ", "_"))


def matchups(c, cle, pos, lanes, nom_de, cle_de):
    """Liste complète des matchups (clé adverse, parties, victoires de « cle »).
    L'outil de matchup renvoie tous les adversaires de la lane quel que soit l'adversaire demandé."""
    adversaires = [x["key"] for x in lanes[pos] if x["key"] != cle][:3]
    for autre in adversaires:
        for moi in (nom_matchup(nom_de.get(cle, cle)), cle_opgg(cle)):
            try:
                g, _ = c.appeler("lol_get_lane_matchup_guide", lang="en_US", position=pos,
                                 my_champion=moi, opponent_champion=nom_matchup(nom_de.get(autre, autre)))
            except Exception:
                continue
            cnt = ((g or {}).get("data") or {}).get("counters") or []
            return [[cle_de.get(x["champion_name"]), x["play"], x["win"]] for x in cnt
                    if cle_de.get(x["champion_name"]) and x.get("play")]
    raise RuntimeError("matchups introuvables")


def main():
    c = OpggMCP()
    champs, _ = c.appeler("lol_list_champions", lang="en_US", desired_output_fields=["data.champions[].{key,name}"])
    # La liste contient aussi des variantes de mode de jeu (« Jade_Malphite ») : on garde la clé normale.
    cle_de = {}
    for x in champs["data"]["champions"]:
        if "_" not in x["key"] and x["name"] not in cle_de:
            cle_de[x["name"]] = x["key"]
    nom_de = {v: k for k, v in cle_de.items()}

    lanes, a_faire = {}, []
    for pos in POSITIONS:
        d, _ = c.appeler("lol_list_lane_meta_champions", lang="en_US", position=pos,
                         desired_output_fields=["data.positions.%s[].%s" % (pos, LISTE[0])])
        liste = d["data"]["positions"][pos]
        for x in liste:
            x["key"] = cle_de.get(x["champion"])
        lanes[pos] = [x for x in liste if x["key"]]
        a_faire += [(x["key"], pos) for x in lanes[pos] if (x.get("role_rate") or 0) >= ROLE_RATE_MIN]
        print("%s : %d champions" % (pos, len(lanes[pos])))

    analyses, echecs = {}, []
    for k, (cle, pos) in enumerate(a_faire, 1):
        try:
            d, liens = c.appeler("lol_get_champion_analysis", game_mode="ranked", champion=cle_opgg(cle),
                                 position=pos, lang="fr_FR", desired_output_fields=ANALYSE)
            data = (d or {}).get("data") or {}
            data["lien"] = next((l.split("OP.GG page:")[-1].strip() for l in liens if "op.gg" in l), None)
            # Tous les matchups de la lane : l'outil « matchup guide » renvoie la liste complète des
            # adversaires (parties, victoires), quel que soit l'adversaire demandé.
            try:
                data["matchups"] = matchups(c, cle, pos, lanes, nom_de, cle_de)
            except Exception as e:
                echecs.append("%s %s matchups : %s" % (cle, pos, str(e)[:100]))
            analyses["%s|%s" % (cle, pos)] = data
        except Exception as e:
            echecs.append("%s %s : %s" % (cle, pos, str(e)[:120]))
        if k % 25 == 0:
            print("  %d / %d" % (k, len(a_faire)))

    meta = {"maj": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "source": "OP.GG",
            "lanes": lanes, "analyses": analyses}
    if len(analyses) < 0.8 * len(a_faire):
        sys.exit("Trop d'échecs (%d / %d), meta.js non modifié.\n%s" % (len(echecs), len(a_faire), "\n".join(echecs[:10])))
    with open(SORTIE, "w", encoding="utf-8", newline="\n") as f:
        f.write("window.META = " + json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + ";\n")
    print("%d analyses, %d échecs, %d appels. meta.js : %d Ko" % (len(analyses), len(echecs), c.n, os.path.getsize(SORTIE) // 1024))
    for e in echecs[:10]:
        print("  échec", e)


if __name__ == "__main__":
    main()
