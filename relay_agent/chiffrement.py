"""Chiffrement des blobs, contrat partagé avec l'app : nonce(12) || AES-256-GCM(cle, nonce, clair, aad = id || nom)."""

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def chiffrer(cle: bytes, id: str, nom: str, clair: bytes, nonce: bytes | None = None) -> bytes:
    nonce = nonce or os.urandom(12)
    return nonce + AESGCM(cle).encrypt(nonce, clair, (id + nom).encode())


def dechiffrer(cle: bytes, id: str, nom: str, blob: bytes) -> bytes:
    if len(blob) < 12 + 16:
        raise ValueError("blob trop court")
    try:
        return AESGCM(cle).decrypt(blob[:12], blob[12:], (id + nom).encode())
    except InvalidTag:
        raise ValueError("blob illisible : clé différente, nom différent ou contenu altéré") from None
