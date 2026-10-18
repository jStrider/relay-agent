"""Pont sans secret pour un agent en bac à sable : tourne sur l'hôte avec la phrase, n'écoute que sur une adresse
locale ou de pont Docker, et n'offre que sync, rafraichir, seance et etat. Rien de ce qu'il renvoie ne contient la phrase."""

import ipaddress
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import rafraichir, sync
from .client import Relais


def adresse_autorisee(adresse: str) -> bool:
    try:
        ip = ipaddress.ip_address(adresse)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private and not ip.is_unspecified


def creer(adresse: str, port: int, relais: Relais, dest: Path) -> ThreadingHTTPServer:
    if not adresse_autorisee(adresse):
        raise ValueError(f"le pont n'écoute que sur une adresse locale ou de pont Docker, pas {adresse!r}")
    dest = Path(dest)
    verrou = threading.Lock()  # un seul accès à dest/ à la fois : deux /sync simultanés se marcheraient dessus

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def repondre(self, code: int, corps):
            data = json.dumps(corps, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path.rstrip("/") == "/etat":
                with verrou:
                    etat = dest / "sante" / "etat.json"
                    if not etat.exists():
                        return self.repondre(404, {"status": "aucune synchro"})
                    try:
                        return self.repondre(200, json.loads(etat.read_text()))
                    except ValueError:
                        return self.repondre(500, {"status": "etat.json illisible"})
            self.repondre(404, {"status": "introuvable"})

        def do_POST(self):
            chemin = self.path.rstrip("/")
            longueur = int(self.headers.get("Content-Length") or 0)
            corps = self.rfile.read(longueur) if longueur else b""
            try:
                if chemin == "/sync":
                    with verrou:
                        rapport = sync.synchroniser(relais, dest, journal=lambda m: None)
                    return self.repondre(200, {"blobs_lus": rapport.blobs_lus, "blobs_ignores": rapport.blobs_ignores})
                if chemin == "/rafraichir":
                    return self.repondre(200, rafraichir.demander(relais))
                if chemin == "/seance":
                    from .cli import executer_seance
                    try:
                        args = json.loads(corps or b"{}").get("args", [])
                    except ValueError:
                        return self.repondre(400, {"status": "JSON attendu : {\"args\": [...]}"})
                    with verrou:
                        code, sortie = executer_seance([str(a) for a in args], dest, relais)
                    return self.repondre(200, {"code": code, "sortie": sortie})
            except Exception as e:  # jamais de trace, jamais la phrase
                return self.repondre(500, {"status": f"erreur : {type(e).__name__}"})
            self.repondre(404, {"status": "introuvable"})

    return ThreadingHTTPServer((adresse, port), Handler)
