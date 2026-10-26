"""Un relais en mémoire pour les tests : mêmes routes et codes que relay-serveur, sans chiffrement côté serveur."""

import base64
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


class FauxRelais:
    def __init__(self, jeton="a" * 43, abonne=True, rafraichir=(200, {"rafraichi": True, "status": "rafraîchi"})):
        self.blobs: dict[str, tuple[bytes, float]] = {}
        self.appairages: dict[str, dict] = {}
        self.jeton, self.abonne, self.reponse_rafraichir = jeton, abonne, rafraichir
        self.requetes = []
        self.messages: list[str] = []
        self.refuser_429 = 0
        self.substituer = None  # "app" ou "agent" : le relais présente à l'autre partie une clé à lui à la place de celle-ci
        self.cle_intruse = base64.urlsafe_b64encode(X25519PrivateKey.generate().public_key().public_bytes_raw()).decode().rstrip("=")
        relais = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def envoyer(self, code, corps=b"", type_="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", type_)
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def autorise(self):
                if relais.refuser_429 > 0:
                    relais.refuser_429 -= 1
                    self.envoyer(429, '{"status":"trop de requetes"}'.encode())
                    return False
                if self.headers.get("Authorization") != f"Bearer {relais.jeton}":
                    self.envoyer(401, b'{"detail":"jeton invalide"}')  # format FastAPI (HTTPException)
                    return False
                return True

            def do_GET(self):
                relais.requetes.append(("GET", self.path))
                if self.path.startswith("/appairages/"):
                    s = relais.appairages.get(self.path.split("/")[2].upper().replace("-", ""))
                    if s is None:
                        return self.envoyer(404, b'{"detail":"session inconnue"}')
                    agent, app = s["agent"], s["app"]
                    if relais.substituer == "agent" and agent:
                        agent = relais.cle_intruse
                    if relais.substituer == "app" and app:
                        app = relais.cle_intruse
                    return self.envoyer(200, json.dumps({"engagement": s["engagement"], "cle_publique_agent": agent, "cle_publique_app": app,
                                                         "identite_chiffree": s["identite"]}).encode())
                if not self.autorise():
                    return
                if self.path.startswith("/blobs?") or self.path == "/blobs":
                    depuis = 0.0
                    if "depuis=" in self.path:
                        depuis = float(self.path.split("depuis=")[1])
                    liste = [{"nom": n, "taille": len(c), "maj": m} for n, (c, m) in relais.blobs.items() if m >= depuis]
                    return self.envoyer(200, json.dumps(liste).encode())
                nom = self.path[len("/blobs/"):]
                if nom in relais.blobs:
                    return self.envoyer(200, relais.blobs[nom][0], "application/octet-stream")
                self.envoyer(404, b'{"status":"blob absent"}')

            def do_PUT(self):
                relais.requetes.append(("PUT", self.path))
                if self.path.startswith("/appairages/"):
                    _, _, session, quoi = self.path.split("/")
                    s = relais.appairages.get(session.upper().replace("-", ""))
                    corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                    if s is None:
                        return self.envoyer(404, b'{"detail":"session inconnue"}')
                    if quoi == "app":
                        if s["app"]:
                            return self.envoyer(409, b'{"detail":"posee"}')
                        s["app"] = corps["cle_publique_app"]
                    elif quoi == "agent":
                        if not s["app"] or s["agent"]:
                            return self.envoyer(409, b'{"detail":"cle de l app absente ou cle agent posee"}')
                        cle = corps["cle_publique_agent"]
                        hache = base64.urlsafe_b64encode(hashlib.sha256(base64.urlsafe_b64decode(cle + "=")).digest()).decode().rstrip("=")
                        if hache != s["engagement"]:
                            return self.envoyer(400, b'{"detail":"engagement non tenu"}')
                        s["agent"] = cle
                    else:
                        s["identite"] = corps["identite_chiffree"]
                    return self.envoyer(200, b'{"status":"ok"}')
                if not self.autorise():
                    return
                nom = self.path[len("/blobs/"):]
                corps = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                if nom == "prevu.json" and not relais.abonne:
                    return self.envoyer(402, b'{"detail":"abonnement requis"}')
                relais.blobs[nom] = (corps, time.time())
                self.envoyer(200, json.dumps({"maj": relais.blobs[nom][1]}).encode())

            def do_DELETE(self):
                relais.requetes.append(("DELETE", self.path))
                if self.path.startswith("/appairages/"):
                    return self.envoyer(204 if relais.appairages.pop(self.path.split("/")[2].upper(), None) else 404)
                if not self.autorise():
                    return
                nom = self.path[len("/blobs/"):]
                self.envoyer(204 if relais.blobs.pop(nom, None) else 404)

            def do_POST(self):
                relais.requetes.append(("POST", self.path))
                if self.path == "/appairages":
                    corps = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                    session = "K7Q2M6XA" if not relais.appairages else "ABCDEFGH"
                    relais.appairages[session] = {"engagement": corps["engagement"], "agent": None, "app": None, "identite": None}
                    return self.envoyer(201, json.dumps({"session": session}).encode())
                if not self.autorise():
                    return
                if self.path == "/rafraichir":
                    if not relais.abonne:
                        return self.envoyer(402, b'{"detail":"abonnement requis"}')
                    code, corps = relais.reponse_rafraichir
                    return self.envoyer(code, json.dumps(corps).encode())
                if self.path == "/messages":
                    if not relais.abonne:
                        return self.envoyer(402, b'{"detail":"abonnement requis"}')
                    relais.messages.append(json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))["chiffre"])
                    return self.envoyer(200, b'{"status":"envoy\xc3\xa9"}')
                self.envoyer(404, b"{}")

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}"

    def arreter(self):
        self.serveur.shutdown()
        self.serveur.server_close()
