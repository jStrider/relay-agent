"""Un relais en mémoire pour les tests : mêmes routes et codes que relay-serveur, sans chiffrement côté serveur."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FauxRelais:
    def __init__(self, jeton="a" * 43, abonne=True, rafraichir=(200, {"rafraichi": True, "status": "rafraîchi"})):
        self.blobs: dict[str, tuple[bytes, float]] = {}
        self.jeton, self.abonne, self.reponse_rafraichir = jeton, abonne, rafraichir
        self.requetes = []
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
                if self.headers.get("Authorization") != f"Bearer {relais.jeton}":
                    self.envoyer(401, b'{"detail":"jeton invalide"}')  # format FastAPI (HTTPException)
                    return False
                return True

            def do_GET(self):
                relais.requetes.append(("GET", self.path))
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
                if not self.autorise():
                    return
                nom = self.path[len("/blobs/"):]
                self.envoyer(204 if relais.blobs.pop(nom, None) else 404)

            def do_POST(self):
                relais.requetes.append(("POST", self.path))
                if not self.autorise():
                    return
                if self.path == "/rafraichir":
                    if not relais.abonne:
                        return self.envoyer(402, b'{"detail":"abonnement requis"}')
                    code, corps = relais.reponse_rafraichir
                    return self.envoyer(code, json.dumps(corps).encode())
                self.envoyer(404, b"{}")

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.serveur.server_address[1]}"

    def arreter(self):
        self.serveur.shutdown()
        self.serveur.server_close()
