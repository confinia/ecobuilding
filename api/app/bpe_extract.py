"""Extraction annuelle des crèches de la BPE (Insee) vers app/creches.json.gz (#473).

L'annuaire de l'éducation commence à la maternelle : les crèches n'y sont pas.
La Base permanente des équipements (Insee, Licence Ouverte) les recense sous le
code D502 « établissement d'accueil du jeune enfant » : 12 814 en 2025, tous
nommés, 99,8 % géolocalisés, capacité renseignée. Ce n'est PAS un inventaire
exhaustif — la fiche le dit.

Un millésime par an, donc un artefact COMMITTÉ plutôt qu'un fichier de 170 Mo
lu à l'exécution (VM partagée saturée en IOPS, #467) — même forme que le REI
(#456). pyarrow ne sert qu'ici, jamais dans l'image de l'API :

    pip install pyarrow httpx
    python -m app.bpe_extract [--year 2025]        (depuis api/)

Produit app/creches.json.gz : {"year": 2025, "creches": [[nom, lon, lat,
capacite, depcom], ...]} — coordonnées à 5 décimales (~1 m), assez pour une
distance, pas assez pour faire croire à une précision que la source n'a pas.
"""
import argparse
import gzip
import io
import json
import os

import httpx

BPE_URLS = {
    2025: "https://www.insee.fr/fr/statistiques/fichier/8217525/BPE25.parquet",
}
TYPEQU_CRECHE = "D502"
OUT = os.path.join(os.path.dirname(__file__), "creches.json.gz")


def parse(parquet_bytes: bytes) -> list:
    """Les crèches géolocalisées, triées pour un fichier stable d'un tirage à
    l'autre. Une ligne sans coordonnées ne peut servir à aucune distance."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    t = pq.read_table(io.BytesIO(parquet_bytes),
                      columns=["TYPEQU", "NOMRS", "CNOMRS", "LONGITUDE",
                               "LATITUDE", "CAPACITE", "DEPCOM"])
    t = t.filter(pc.equal(t["TYPEQU"], TYPEQU_CRECHE))
    out = []
    for r in t.to_pylist():
        if r["LONGITUDE"] is None or r["LATITUDE"] is None:
            continue
        nom = (r["NOMRS"] or r["CNOMRS"] or "").strip()
        try:
            capacite = int(float(r["CAPACITE"])) if r["CAPACITE"] not in (None, "") else None
        except ValueError:
            capacite = None
        out.append([nom, round(float(r["LONGITUDE"]), 5), round(float(r["LATITUDE"]), 5),
                    capacite, r["DEPCOM"]])
    out.sort(key=lambda c: (c[4] or "", c[0], c[1], c[2]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=max(BPE_URLS))
    a = ap.parse_args()
    print(f"BPE {a.year}: téléchargement…")
    brut = httpx.get(BPE_URLS[a.year], timeout=900, follow_redirects=True).content
    creches = parse(brut)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump({"year": a.year, "creches": creches}, f,
                  ensure_ascii=False, separators=(",", ":"))
    print(f"{len(creches)} crèches → {OUT} ({os.path.getsize(OUT) // 1024} Ko)")


if __name__ == "__main__":
    main()
