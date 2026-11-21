"""Avis du coach écrit par Claude Code (sans clé API Anthropic).

  python scripts/texte_debrief.py a-rediger [N]          # affiche les N parties récentes sans avis (défaut 6), avec leur analyse
  python scripts/texte_debrief.py ecrire FICHIER.json    # enregistre des avis : {"<match_id>": {texte}, ...}

Le texte suit le même format que scripts/debrief.py (SCHEMA) et les mêmes règles (SYSTEME).
Lancer d'abord `python scripts/debrief.py --sans-ia` pour produire l'analyse des nouvelles parties.
"""
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import debrief as D  # noqa: E402


def sauver(deb):
    with open(D.SORTIE, "w", encoding="utf-8", newline="\n") as f:
        f.write(D.PREFIXE + json.dumps(deb, ensure_ascii=False, separators=(",", ":")) + ";\n")


def valider(t):
    s = D.SCHEMA
    manquants = [k for k in s["required"] if k not in t]
    if manquants:
        raise ValueError("champs manquants : " + ", ".join(manquants))
    if t["responsabilite"] not in s["properties"]["responsabilite"]["enum"]:
        raise ValueError("responsabilite invalide : " + t["responsabilite"])
    for m in t["moments_cles"]:
        if not isinstance(m.get("minute"), int) or not m.get("texte"):
            raise ValueError("moment_cle invalide : %r" % m)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    deb = D.charger()
    if sys.argv[1] == "a-rediger":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
        l = sorted([(k, v) for k, v in deb.items() if not v.get("texte")], key=lambda kv: kv[1]["analyse"]["date"], reverse=True)[:n]
        print("RÈGLES DU COACH :\n" + D.SYSTEME + "\n\nFORMAT (JSON) :\n" + json.dumps(D.SCHEMA, ensure_ascii=False))
        for k, v in l:
            print("\n=== %s ===\n%s" % (k, json.dumps(v["analyse"], ensure_ascii=False)))
        if not l:
            print("\nAucune partie sans avis.")
    elif sys.argv[1] == "ecrire":
        textes = json.load(open(sys.argv[2], encoding="utf-8"))
        for k, t in textes.items():
            if k not in deb:
                print("inconnu, ignoré :", k)
                continue
            valider(t)
            deb[k]["texte"] = t
            deb[k]["genere"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
            print("avis enregistré :", k)
        sauver(deb)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
