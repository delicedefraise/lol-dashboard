"""Compagnon de partie — à lancer sur le PC où tu joues.

Il lit l'API locale officielle de Riot (Live Client Data, https://127.0.0.1:2999), qui ne
contient que ce que le jeu t'affiche déjà (touche Tab, kill feed), et sert une page sur ton
Wi-Fi : ouvre l'adresse affichée sur ton téléphone. Aucune lecture d'écran ni de mémoire,
aucune action dans le jeu.

Usage :
  python compagnon.py           # partie réelle
  python compagnon.py --demo    # partie fictive pour tester la page sans jouer
  python compagnon.py --port 8777
Bibliothèque standard Python uniquement.
"""
import argparse
import json
import os
import socket
import ssl
import sys
import time
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ICI = os.path.dirname(os.path.abspath(__file__))
API = "https://127.0.0.1:2999/liveclientdata/allgamedata"

# Le client du jeu utilise un certificat local auto-signé : on ne désactive la vérification
# que pour cette adresse locale.
SSL_LOCAL = ssl.create_default_context()
SSL_LOCAL.check_hostname = False
SSL_LOCAL.verify_mode = ssl.CERT_NONE

DEMO = None
DEBUT_DEMO = time.time()


def etat_partie():
    if DEMO is not None:
        d = json.loads(json.dumps(DEMO))
        d["gameData"]["gameTime"] = d["gameData"].get("gameTime", 600) + (time.time() - DEBUT_DEMO)
        return {"enJeu": True, "demo": True, "data": d}
    try:
        with urllib.request.urlopen(API, timeout=1.5, context=SSL_LOCAL) as r:
            data = json.loads(r.read().decode("utf-8"))
        if not data.get("allPlayers"):
            return {"enJeu": False, "chargement": True}
        return {"enJeu": True, "data": data}
    except Exception:
        return {"enJeu": False}


class Pages(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _envoyer(self, code, corps, type_):
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        chemin = self.path.split("?")[0]
        if chemin in ("/", "/index.html"):
            with open(os.path.join(ICI, "compagnon.html"), "rb") as f:
                return self._envoyer(200, f.read(), "text/html; charset=utf-8")
        if chemin == "/etat":
            return self._envoyer(200, json.dumps(etat_partie()).encode("utf-8"), "application/json")
        self._envoyer(404, b"introuvable", "text/plain")


def ip_locale():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # aucune donnée envoyée : sert juste à trouver l'interface Wi-Fi
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    global DEMO
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--demo", action="store_true", help="partie fictive pour tester la page")
    a = ap.parse_args()
    if a.demo:
        with open(os.path.join(ICI, "demo.json"), encoding="utf-8") as f:
            DEMO = json.load(f)
    serveur = ThreadingHTTPServer(("0.0.0.0", a.port), Pages)
    url = "http://%s:%d" % (ip_locale(), a.port)
    print("")
    print("  Compagnon de partie lancé%s." % (" (mode démo)" if a.demo else ""))
    print("  Sur ton téléphone, connecté au même Wi-Fi, ouvre :  %s" % url)
    print("  Sur ce PC :  http://localhost:%d" % a.port)
    print("  Laisse cette fenêtre ouverte pendant tes parties. Ctrl+C pour arrêter.")
    print("")
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        print("Arrêt.")
        sys.exit(0)


if __name__ == "__main__":
    main()
