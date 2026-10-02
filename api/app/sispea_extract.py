"""Extraction des indicateurs d'eau potable de l'observatoire SISPEA (#486).

Hub'Eau a décommissionné son API « indicateurs des services » le 10/09/2026
(410 Gone) et renvoie vers l'Observatoire national des services d'eau et
d'assainissement (services.eaufrance.fr), qui publie en open data (Licence
Ouverte), par exercice :
  - openData/SISPEA_FR_<année>_AEP.zip : une ligne par entité de gestion, avec
    P104.3 (rendement du réseau de distribution, %) et D102.0 (prix TTC au m³
    pour 120 m³) ;
  - serviceMembers/CompositionCommunaleServices_AEP_<année>.zip : quelle
    commune adhère à quelle entité de gestion.

Les services déclarent avec un an de retard : l'exercice le plus récent est
lacunaire (2025 : 1 575 rendements sur 9 229 services, contre 8 067 pour
2024). Chaque commune reçoit donc l'exercice le PLUS RÉCENT où son service a
déclaré un rendement, et la fiche affiche cet exercice.

Un artefact COMMITTÉ, refait une fois par an, comme le REI (#456) et la BPE
(#473). xlrd et openpyxl ne servent qu'ici, jamais dans l'image de l'API :

    pip install xlrd openpyxl httpx
    python -m app.sispea_extract [--years 2023 2024 2025]     (depuis api/)

Produit app/eau.json.gz : {"years": [...], "communes": {"31557": [rendement,
prix, exercice, nom_commune], ...}}.
"""
import argparse
import gzip
import io
import json
import os
import zipfile

import httpx

BASE = "https://www.services.eaufrance.fr/documents"
OUT = os.path.join(os.path.dirname(__file__), "eau.json.gz")


def _insee(v) -> str | None:
    """1001.0 -> « 01001 » ; « 2A004 » inchangé."""
    if v in (None, ""):
        return None
    if isinstance(v, float):
        return f"{int(v):05d}"
    s = str(v).strip()
    return s.zfill(5) if s.isdigit() else s


def _num(v):
    try:
        return float(v) if str(v).strip() not in ("", "NC", "None") else None
    except ValueError:
        return None


def indicateurs(xls_bytes: bytes) -> dict:
    """{id entité de gestion: (rendement, prix, nom)} pour un exercice."""
    import xlrd

    sh = xlrd.open_workbook(file_contents=xls_bytes, on_demand=True) \
        .sheet_by_name("Entités de gestion")
    tete = sh.row_values(0)
    i_id = tete.index("Id SISPEA de l'entité de gestion")
    i_p104, i_d102 = tete.index("P104.3"), tete.index("D102.0")
    out = {}
    for r in range(1, sh.nrows):
        ident = sh.cell_value(r, i_id)
        if ident in ("", None):
            continue
        out[str(int(float(ident)))] = (_num(sh.cell_value(r, i_p104)),
                                       _num(sh.cell_value(r, i_d102)))
    return out


def composition(xlsx_bytes: bytes) -> dict:
    """{insee: [(id entité, population représentative, nom commune)]}."""
    import openpyxl

    ws = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True).active
    lignes = ws.iter_rows(values_only=True)
    tete = list(next(lignes))
    i_insee = tete.index("Code INSEE de la commune adhérente")
    i_nom = tete.index("Nom de la commune adhérente")
    i_ent = tete.index("Identifiant SISPEA de l'entité de gestion à laquelle la commune adhère")
    i_pop = tete.index("Population représentative")
    out: dict = {}
    for l in lignes:
        insee, ent = _insee(l[i_insee]), l[i_ent]
        if not insee or ent in (None, ""):
            continue
        out.setdefault(insee, []).append(
            (str(int(float(ent))), _num(l[i_pop]) or 0, l[i_nom]))
    return out


def fusion(par_annee: dict) -> dict:
    """par_annee = {année: (indicateurs, composition)} -> {insee: [rendement,
    prix, exercice, nom]}. Pour chaque commune, l'exercice le plus récent où
    une de ses entités a déclaré un rendement ; plusieurs entités (secteurs) :
    celle qui dessert la plus grande population."""
    communes: dict = {}
    for annee in sorted(par_annee, reverse=True):
        ind, comp = par_annee[annee]
        for insee, entites in comp.items():
            if insee in communes:
                continue
            candidates = [(pop, ent, nom) for ent, pop, nom in entites
                          if ind.get(ent, (None, None))[0] is not None]
            if not candidates:
                continue
            _pop, ent, nom = max(candidates, key=lambda c: (c[0], c[1]))
            rendement, prix = ind[ent]
            communes[insee] = [round(rendement, 1),
                               round(prix, 2) if prix is not None else None,
                               annee, nom]
    return communes


def _zip_unique(url: str) -> bytes:
    z = zipfile.ZipFile(io.BytesIO(httpx.get(url, timeout=600, follow_redirects=True).content))
    return z.read(z.namelist()[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, nargs="+", default=[2023, 2024, 2025])
    a = ap.parse_args()
    par_annee = {}
    for y in a.years:
        print(f"SISPEA {y}: téléchargement…")
        ind = indicateurs(_zip_unique(f"{BASE}/openData/SISPEA_FR_{y}_AEP.zip"))
        comp = composition(_zip_unique(
            f"{BASE}/serviceMembers/CompositionCommunaleServices_AEP_{y}.zip"))
        par_annee[y] = (ind, comp)
    communes = fusion(par_annee)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump({"years": sorted(a.years), "communes": communes}, f,
                  ensure_ascii=False, separators=(",", ":"))
    print(f"{len(communes)} communes → {OUT} ({os.path.getsize(OUT) // 1024} Ko)")


if __name__ == "__main__":
    main()
