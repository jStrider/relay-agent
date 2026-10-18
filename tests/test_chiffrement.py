import json
from pathlib import Path

import pytest

from relay_agent import chiffrement

VECTEURS = json.loads((Path(__file__).parent.parent / "vecteurs" / "chiffrement.json").read_text())


@pytest.mark.parametrize("v", VECTEURS, ids=[v["nom"] for v in VECTEURS])
def test_vecteurs_rejoues(v):
    cle = bytes.fromhex(v["cle"])
    blob = chiffrement.chiffrer(cle, v["id"], v["blob"], bytes.fromhex(v["clair"]), nonce=bytes.fromhex(v["nonce"]))
    assert blob.hex() == v["blob_chiffre"]
    assert chiffrement.dechiffrer(cle, v["id"], v["blob"], blob) == bytes.fromhex(v["clair"])


def test_nonce_aleatoire_par_defaut():
    cle = bytes(32)
    a = chiffrement.chiffrer(cle, "ID", "etat.json", b"x")
    b = chiffrement.chiffrer(cle, "ID", "etat.json", b"x")
    assert a != b and len(a) == 12 + 1 + 16


def test_blob_altere_refuse():
    v = VECTEURS[1]
    blob = bytearray.fromhex(v["blob_chiffre"])
    blob[20] ^= 1
    with pytest.raises(ValueError):
        chiffrement.dechiffrer(bytes.fromhex(v["cle"]), v["id"], v["blob"], bytes(blob))


def test_aad_lie_le_nom():
    v = VECTEURS[1]
    with pytest.raises(ValueError):
        chiffrement.dechiffrer(bytes.fromhex(v["cle"]), v["id"], "metriques/step_count/2026-11.json", bytes.fromhex(v["blob_chiffre"]))
