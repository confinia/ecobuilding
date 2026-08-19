"""Rafraîchissement mensuel des DIA de Montpellier Méditerranée Métropole (#246).

Les Déclarations d'Intention d'Aliéner sont transmises par les notaires AU
MOMENT d'une vente (droit de préemption) : c'est un indicateur AVANCÉ du
marché, là où DVF publie avec ~un semestre de retard. Publication mensuelle,
licence Open Data — https://data.montpellier3m.fr/

Produit DIA_PATH (défaut /leads/dia.json) :
  - Montpellier-ville : agrégats par SOUS-QUARTIER, avec le polygone WGS84
    (le rattachement bâtiment se fait en point-in-polygon côté API) ;
  - les 30 autres communes : agrégats par commune, jointure par code INSEE
    (le xlsx ne donne pas de sous-quartier hors Montpellier).

⚠ Le « montant » DIA est le prix de MISE EN VENTE déclaré, pas le prix de
vente final — tout affichage doit le dire (le champ s'appelle asking_*).

Usage : python -m app.dia_refresh   (dans le conteneur API ; openpyxl requis)
"""
import io
import json
import os
import statistics
from datetime import datetime, timedelta, timezone

import httpx

DIA_XLSX_URL = os.environ.get(
    "DIA_XLSX_URL",
    "https://data.montpellier3m.fr/sites/default/files/ressources/MMM_MMM_DIA.xlsx")
SUBQ_GEOJSON_URL = os.environ.get(
    "DIA_SUBQ_URL",
    "https://data.montpellier3m.fr/sites/default/files/ressources/VilleMTP_MTP_SousQuartiers.json")
# Communes de l'EPCI (noms officiels + INSEE) — évite une table en dur.
EPCI_COMMUNES_URL = "https://geo.api.gouv.fr/epcis/243400017/communes?fields=code,nom"
DIA_PATH = os.environ.get("DIA_PATH", "/leads/dia.json")
UA = {"User-Agent": "ecobuilding/1.0 (contact@confinia.io)"}


def _norm(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def _median(values):
    values = [v for v in values if v]
    return round(statistics.median(values)) if values else None


def refresh() -> dict:
    import openpyxl

    with httpx.Client(timeout=180, headers=UA, follow_redirects=True) as c:
        xlsx = c.get(DIA_XLSX_URL).raise_for_status().content
        subq = c.get(SUBQ_GEOJSON_URL).raise_for_status().json()
        communes = c.get(EPCI_COMMUNES_URL).raise_for_status().json()
    insee_by_name = {_norm(x["nom"]): x["code"] for x in communes}

    wb = openpyxl.load_workbook(io.BytesIO(xlsx), read_only=True)
    rows = wb.active.iter_rows(values_only=True)
    header = [str(h) for h in next(rows)]
    col = {name: header.index(name) for name in (
        "Sous quartiers", "Reçu en mairie", "Montant mise en vente",
        "Surface utile", "Désignation du bien")}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    w12, w3 = now - timedelta(days=365), now - timedelta(days=91)
    buckets: dict = {}
    for r in rows:
        zone = r[col["Sous quartiers"]]
        received = r[col["Reçu en mairie"]]
        if not zone or not isinstance(received, datetime) or received < w12:
            continue
        try:
            amount = float(str(r[col["Montant mise en vente"]]).replace(",", "."))
        except (TypeError, ValueError):
            amount = None
        try:
            surface = float(str(r[col["Surface utile"]]).replace(",", "."))
        except (TypeError, ValueError):
            surface = None
        kind = (r[col["Désignation du bien"]] or "Autre").strip()
        b = buckets.setdefault(zone, {"n_12m": 0, "n_3m": 0, "amounts": [],
                                      "eur_m2": [], "types": {}})
        b["n_12m"] += 1
        if received >= w3:
            b["n_3m"] += 1
        # Garde-fous : les montants symboliques (1 €…) et les surfaces
        # aberrantes ne doivent pas polluer les médianes.
        if amount and amount >= 10_000:
            b["amounts"].append(amount)
            if surface and surface >= 9:
                b["eur_m2"].append(amount / surface)
        b["types"][kind] = b["types"].get(kind, 0) + 1

    zones = []
    polygons = {f["properties"]["name"]: f["geometry"]
                for f in subq.get("features", [])}
    for zone, b in buckets.items():
        entry = {"name": zone, "n_12m": b["n_12m"], "n_3m": b["n_3m"],
                 "median_asking_eur": _median(b["amounts"]),
                 "median_asking_eur_m2": _median(b["eur_m2"]),
                 "types": dict(sorted(b["types"].items(),
                                      key=lambda kv: -kv[1])[:4])}
        if zone in polygons:                       # sous-quartier de Montpellier
            entry["polygon"] = polygons[zone]
            entry["commune"] = "Montpellier"
        elif zone.endswith("sous-quartier inconnu"):
            name = zone.removesuffix("sous-quartier inconnu").strip()
            insee = insee_by_name.get(_norm(name))
            if not insee:
                continue                            # commune hors EPCI/typo : on ignore
            entry["name"] = name.title()
            entry["commune_insee"] = insee
        else:
            continue
        zones.append(entry)

    out = {"updated": now.strftime("%Y-%m-%d"),
           "source": "Déclarations d'Intention d'Aliéner — Montpellier "
                     "Méditerranée Métropole (Open Data), montants de MISE EN "
                     "VENTE déclarés",
           "zones": zones}
    os.makedirs(os.path.dirname(DIA_PATH), exist_ok=True)
    tmp = DIA_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f, ensure_ascii=False)
    os.replace(tmp, DIA_PATH)
    return out


if __name__ == "__main__":
    d = refresh()
    subq = sum(1 for z in d["zones"] if "polygon" in z)
    print(f"DIA: {len(d['zones'])} zones ({subq} sous-quartiers Montpellier, "
          f"{len(d['zones']) - subq} communes), maj {d['updated']} -> {DIA_PATH}")
