"""Extraction annuelle de la « Carte des loyers » vers app/loyers.json.gz (#518).

Le ministère (DHUP, avec l'ANIL et SeLoger/leboncoin) publie chaque année, par
commune, le loyer d'annonce PRÉDIT au m² — charges comprises — pour les
appartements (tous, 1-2 pièces, 3 pièces et plus) et les maisons, avec son
intervalle de prédiction à 95 %. Paris, Lyon et Marseille par
arrondissement, comme les codes BDNB.

C'est un modèle d'annonces, pas un loyer signé : la fiche le dit. `TYPPRED`
précise le niveau de l'estimation — « commune » quand les annonces de la
commune suffisent, « maille » quand le modèle s'appuie sur un regroupement de
communes voisines — et `nbobs_com` le nombre d'annonces de la commune.

Un millésime par an, donc un artefact COMMITTÉ plutôt qu'un téléchargement à
l'exécution (règle 24, disque de la VM partagée), comme REI et SISPEA.

Usage : python -m app.loyers_extract   (depuis api/, réseau requis)
Produit app/loyers.json.gz : {"year": 2025, "communes": {"31149": {"app": [pred,
bas, haut, "commune", nb_annonces], "app12": [...], "app3": [...], "mai": [...]}}}
"""
import csv
import gzip
import io
import json
import os

import httpx

ANNEE = 2025
BASE = ("https://static.data.gouv.fr/resources/"
        "carte-des-loyers-indicateurs-de-loyers-dannonce-par-commune-en-2025/")
FICHIERS = {
    "app": BASE + "20251211-145010/pred-app-mef-dhup.csv",
    "app12": BASE + "20251211-144934/pred-app12-mef-dhup.csv",
    "app3": BASE + "20251211-144951/pred-app3-mef-dhup.csv",
    "mai": BASE + "20251211-145039/pred-mai-mef-dhup.csv",
}
OUT = os.path.join(os.path.dirname(__file__), "loyers.json.gz")


def _num(s: str) -> float | None:
    s = (s or "").strip().replace(",", ".")
    return float(s) if s else None


def parse(contenu: bytes) -> dict:
    """{insee: [prédit, bas, haut, niveau, annonces_commune]} pour un fichier."""
    rows = csv.DictReader(io.StringIO(contenu.decode("latin-1")), delimiter=";")
    out = {}
    for r in rows:
        pred = _num(r.get("loypredm2"))
        if pred is None:
            continue
        out[r["INSEE_C"].strip()] = [
            round(pred, 1), round(_num(r.get("lwr.IPm2")) or 0, 1),
            round(_num(r.get("upr.IPm2")) or 0, 1),
            (r.get("TYPPRED") or "").strip(), int(_num(r.get("nbobs_com")) or 0)]
    return out


def main():
    communes: dict = {}
    for cle, url in FICHIERS.items():
        print(f"{cle}: {url}")
        for insee, v in parse(httpx.get(url, timeout=120, follow_redirects=True).content).items():
            communes.setdefault(insee, {})[cle] = v
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump({"year": ANNEE, "communes": communes}, f, separators=(",", ":"))
    print(f"{len(communes)} communes → {OUT} ({os.path.getsize(OUT) // 1024} Ko)")


if __name__ == "__main__":
    main()
