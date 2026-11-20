"""Petit client pour le serveur MCP public d'OP.GG (https://mcp-api.op.gg/mcp).

Le serveur répond dans un format texte compact :
    class Foo: a,b
    class Bar: x
    Foo(1,Bar("txt"))
que `analyser()` transforme en dictionnaires et listes Python.
Aucune dépendance : bibliothèque standard uniquement.
"""
import json
import re
import ssl
import time
import urllib.request

try:
    import certifi
    SSL = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL = ssl.create_default_context()

URL = "https://mcp-api.op.gg/mcp"
CLIENT = "lol-dashboard/1.0"


class OpggMCP:
    def __init__(self):
        self.session = None
        self.n = 0
        self._init()

    def _post(self, corps, attendre_reponse=True):
        tetes = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                 "MCP-Protocol-Version": "2025-06-18", "User-Agent": CLIENT}
        if self.session:
            tetes["mcp-session-id"] = self.session
        req = urllib.request.Request(URL, data=json.dumps(corps).encode(), headers=tetes, method="POST")
        with urllib.request.urlopen(req, timeout=60, context=SSL) as r:
            if not self.session:
                self.session = r.headers.get("mcp-session-id")
            brut = r.read().decode("utf-8")
            if not attendre_reponse or not brut.strip():
                return None
            if "text/event-stream" in (r.headers.get("Content-Type") or ""):
                lignes = [l[5:].strip() for l in brut.splitlines() if l.startswith("data:")]
                brut = lignes[-1] if lignes else "{}"
            return json.loads(brut)

    def _init(self):
        self._post({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                               "clientInfo": {"name": "lol-dashboard", "version": "1.0"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, attendre_reponse=False)

    def appeler(self, outil, **args):
        args.setdefault("client_app", CLIENT)
        for essai in range(4):
            self.n += 1
            try:
                rep = self._post({"jsonrpc": "2.0", "id": self.n, "method": "tools/call",
                                  "params": {"name": outil, "arguments": args}})
            except Exception as e:  # coupure réseau, session expirée...
                if essai == 3:
                    raise
                time.sleep(3 * (essai + 1))
                self.session = None
                self._init()
                continue
            if "error" in rep:
                raise RuntimeError("%s : %s" % (outil, rep["error"]))
            res = rep.get("result") or {}
            textes = [c.get("text", "") for c in res.get("content", []) if c.get("type") == "text"]
            if res.get("isError"):
                raise RuntimeError("%s : %s" % (outil, " ".join(textes)[:300]))
            return analyser(textes[0] if textes else ""), textes[1:]
        return None, []


# ---------------------------------------------------------------- format compact

_TOKEN = re.compile(r'\s*(?:(?P<str>"(?:[^"\\]|\\.)*")|(?P<num>-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)|(?P<id>[A-Za-z_][A-Za-z0-9_]*)|(?P<p>[()\[\],]))')


def analyser(texte):
    if not texte.strip():
        return None
    if texte.lstrip()[:1] in "{[":  # certains outils répondent directement en JSON
        try:
            return json.loads(texte)
        except ValueError:
            pass
    classes, corps = {}, []
    for ligne in texte.splitlines():
        m = re.match(r"class (\w+):\s*(.*)$", ligne)
        if m:
            classes[m.group(1)] = [c.strip() for c in m.group(2).split(",") if c.strip()]
        elif ligne.strip():
            corps.append(ligne)
    jetons = []
    src, pos = "\n".join(corps), 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m:
            if src[pos:].strip() == "":
                break
            raise ValueError("Format inattendu près de : " + src[pos:pos + 60])
        pos = m.end()
        for k in ("str", "num", "id", "p"):
            if m.group(k) is not None:
                jetons.append((k, m.group(k)))
                break
    i = 0

    def valeur():
        nonlocal i
        k, v = jetons[i]
        if k == "str":
            i += 1
            return json.loads(v)
        if k == "num":
            i += 1
            return float(v) if any(c in v for c in ".eE") else int(v)
        if k == "p" and v == "[":
            i += 1
            out = []
            while jetons[i] != ("p", "]"):
                out.append(valeur())
                if jetons[i] == ("p", ","):
                    i += 1
            i += 1
            return out
        if k == "id":
            i += 1
            if v in ("true", "True"):
                return True
            if v in ("false", "False"):
                return False
            if v in ("null", "None"):
                return None
            if i < len(jetons) and jetons[i] == ("p", "("):
                i += 1
                args = []
                while jetons[i] != ("p", ")"):
                    args.append(valeur())
                    if jetons[i] == ("p", ","):
                        i += 1
                i += 1
                champs = classes.get(v)
                return dict(zip(champs, args)) if champs else args
            return v
        raise ValueError("Jeton inattendu : %r" % (jetons[i],))

    return valeur()
