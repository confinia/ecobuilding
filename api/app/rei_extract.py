"""Extraction annuelle du REI (Recensement des éléments d'imposition à la
fiscalité directe locale, DGFiP) vers app/rei.json.gz (#456).

Le jeu interrogé en direct (fiscalite-locale-des-particuliers-geo) ne publie
que des taux ; le fichier REI, lui, donne par commune les MONTANTS émis et le
NOMBRE D'ARTICLES (un article = un avis de taxe foncière). Leur quotient est
la taxe foncière moyenne par avis dans la commune : un ordre de grandeur en
euros publié par la DGFiP elle-même, jamais la cotisation de tel logement
(#257 : la valeur locative cadastrale n'est pas publique par local).

Un millésime par an, donc un artefact COMMITTÉ plutôt qu'un téléchargement à
l'exécution (règle 24, disque de la VM partagée). Colonnes (TRACE_REI.xlsx) :
  E14  nombre d'articles ayant une base de taxe foncière bâtie (TFB)
  E13, E23, E33, E53, E53A, E53gGEMAPI, E53TASA
       montants TFB émis : commune, syndicats, EPCI, TSE, TSE autres, GEMAPI,
       TASA (Île-de-France) — la somme est ce que paient les avis de la commune
  F13 / F14  montant total TEOM / nombre d'articles TEOM (0 hors TEOM)

Usage : python -m app.rei_extract [--year 2025]   (depuis api/, réseau requis)
Produit app/rei.json.gz : {"year": 2025, "communes": {"11170": [tfb_mean,
tfb_rank_pct, teom_mean, articles], ...}} — arrondissements de Paris, Lyon et
Marseille rattachés à leur commune (une seule ligne REI : 75056, 69123, 13055).
"""
import argparse
import bisect
import csv
import gzip
import io
import json
import os
import zipfile

import httpx

# Pièce jointe du jeu data.economie.gouv.fr « impots-locaux-fichier-de-
# recensement-des-elements-dimposition-a-la-fiscalite-dir » : un zip par
# millésime (csv + TRACE xlsx + notice). Le nom varie d'une année à l'autre
# (2024 : « …_trace_zip »), d'où la liste.
REI_URLS = {
    2025: "https://data.economie.gouv.fr/api/v2/catalog/datasets/impots-locaux-fichier-de-"
          "recensement-des-elements-dimposition-a-la-fiscalite-dir/attachments/"
          "rei_2025_fichier_notice_tracezip",
    2024: "https://data.economie.gouv.fr/api/v2/catalog/datasets/impots-locaux-fichier-de-"
          "recensement-des-elements-dimposition-a-la-fiscalite-dir/attachments/"
          "rei_2024_fichier_notice_trace_zip",
}
AMOUNT_COLS = ["E13", "E23", "E33", "E53", "E53A", "E53gGEMAPI", "E53TASA"]
OUT = os.path.join(os.path.dirname(__file__), "rei.json.gz")


def _num(s: str) -> float:
    s = (s or "").strip().replace(",", ".")
    return float(s) if s else 0.0


def parse(csv_bytes: bytes) -> dict:
    """{insee: [tfb_mean, tfb_rank_pct, teom_mean, articles]} ; les communes
    sans article (données occultées, 87 en 2025) sont absentes."""
    rows = csv.reader(io.TextIOWrapper(io.BytesIO(csv_bytes), encoding="latin-1"),
                      delimiter=";")
    head = next(rows)
    ix = {c: head.index(c) for c in ["DEP", "COM", "E14", "F13", "F14"] + AMOUNT_COLS}
    out = {}
    for r in rows:
        articles = _num(r[ix["E14"]])
        if articles <= 0:
            continue
        # DEP « 2A », « 971 » + COM sur 3 (ou 2 outre-mer) chiffres → INSEE 5.
        dep, com = r[ix["DEP"]].strip(), r[ix["COM"]].strip()
        insee = dep + com.zfill(5 - len(dep))
        tfb = sum(_num(r[ix[c]]) for c in AMOUNT_COLS) / articles
        teom_art = _num(r[ix["F14"]])
        teom = _num(r[ix["F13"]]) / teom_art if teom_art > 0 else None
        out[insee] = [tfb, None, teom, int(articles)]
    means = sorted(v[0] for v in out.values())
    for v in out.values():
        v[1] = round(100 * bisect.bisect_left(means, v[0]) / len(means))
        v[0] = round(v[0])
        v[2] = round(v[2]) if v[2] is not None else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=max(REI_URLS))
    a = ap.parse_args()
    print(f"REI {a.year}: téléchargement…")
    z = zipfile.ZipFile(io.BytesIO(httpx.get(REI_URLS[a.year], timeout=600,
                                             follow_redirects=True).content))
    name = next(n for n in z.namelist() if n.lower().endswith(".csv"))
    communes = parse(z.read(name))
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump({"year": a.year, "communes": communes}, f, separators=(",", ":"))
    print(f"{len(communes)} communes → {OUT} ({os.path.getsize(OUT) // 1024} Ko)")


if __name__ == "__main__":
    main()
