"""EcoBuilding API — per-building intelligence on French open data.

Versioning: all routes live under /v1. Breaking changes will ship as /v2;
/v1 keeps working. The public mount point is /api (stripped by the edge
proxy; root_path keeps the OpenAPI docs URLs correct).

Data sources (all open, keyless):
  - BAN  (api-adresse.data.gouv.fr)   — geocoding, Licence Ouverte
  - BDNB (api.bdnb.io, CSTB)          — per-building attributes, Licence Ouverte v2
  - Géorisques (georisques.gouv.fr)   — natural/technological risks, Licence Ouverte
"""

import logging
import os

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

log = logging.getLogger("ecobuilding")

BAN_URL = "https://api-adresse.data.gouv.fr/search/"
BDNB_URL = "https://api.bdnb.io/v1/bdnb/donnees/batiment_groupe_complet/adresse"
GEORISQUES_URL = "https://georisques.gouv.fr/api/v1/resultats_rapport_risque"

# Rental-ban calendar, loi Climat et Résilience (verified 2026-07-20).
DPE_BAN_DATES = {"G": "2025-01-01", "F": "2028-01-01", "E": "2034-01-01"}

app = FastAPI(
    title="EcoBuilding API",
    version="1.0.0",
    description=(
        "Per-building intelligence for France built on open data: energy class (DPE), "
        "rental-ban status (loi Climat et Résilience), natural risks, construction "
        "attributes and solar potential — one key, one call, one normalized schema.\n\n"
        "Data: BDNB (CSTB), BAN, Géorisques — Licence Ouverte. "
        "Attribution required when redistributing."
    ),
    root_path="/api",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
    redoc_url="/v1/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# --- OpenTelemetry -----------------------------------------------------------
# Metrics flow: SDK -> OTLP/http -> otel-collector -> Prometheus -> Grafana.
# The app must run fine without a collector (local dev): exporter failures are
# logged by the SDK, never raised.
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

_resource = Resource.create({"service.name": "ecobuilding-api"})
_reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=15000)
metrics.set_meter_provider(MeterProvider(resource=_resource, metric_readers=[_reader]))
_meter = metrics.get_meter("ecobuilding")

M_REQUESTS = _meter.create_counter(
    "ecobuilding_api_requests", description="API requests", unit="1"
)
M_LOOKUPS = _meter.create_counter(
    "ecobuilding_lookups", description="Building lookups", unit="1"
)
M_FRONTEND = _meter.create_counter(
    "ecobuilding_frontend_events", description="Frontend usage events", unit="1"
)

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()


@app.middleware("http")
async def count_requests(request, call_next):
    response = await call_next(request)
    M_REQUESTS.add(
        1,
        {
            "route": request.url.path,
            "method": request.method,
            "status": str(response.status_code),
        },
    )
    return response


# --- Helpers -----------------------------------------------------------------

_client = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "ecobuilding.confinia.io"})


def _rental_ban(dpe_class: str | None) -> dict | None:
    if not dpe_class:
        return None
    date = DPE_BAN_DATES.get(dpe_class.upper())
    return {
        "dpe_class": dpe_class.upper(),
        "rental_ban_date": date,
        "note": (
            f"Location interdite à partir du {date} (loi Climat et Résilience)"
            if date
            else "Aucune interdiction de location prévue pour cette classe"
        ),
    }


def _normalize_building(r: dict) -> dict:
    """BDNB batiment_groupe_complet/adresse row -> stable public schema (v1)."""
    return {
        "bdnb_id": r.get("batiment_groupe_id"),
        "address": r.get("libelle_adr_principale_ban"),
        "construction_year": r.get("annee_construction"),
        "height_m": r.get("hauteur_mean"),
        "floors": r.get("nb_niveau"),
        "dwellings": r.get("nb_log"),
        "wall_material": r.get("mat_mur_txt"),
        "roof_material": r.get("mat_toit_txt"),
        "energy": {
            "dpe_class": r.get("classe_bilan_dpe"),
            "dpe_date": r.get("date_reception_dpe"),
            "consumption_kwh_m2y": r.get("conso_5_usages_ep_m2"),
            "ghg_kgco2_m2y": r.get("emission_ges_5_usages_m2"),
            "dpe_class_counts": {
                c: r.get(f"nb_classe_bilan_dpe_{c.lower()}") for c in "ABCDEFG"
            },
            "rental_ban": _rental_ban(r.get("classe_bilan_dpe")),
        },
        "risks": {
            "clay_shrink_swell": r.get("alea_argile"),
        },
        "solar": {
            "thermal_favourable": r.get("batenr_favorabilite_solaire_thermique"),
            "thermal_potential_kwh_y": r.get("batenr_potentiel_prod_solaire_thermique_annuelle"),
        },
        "consumption_2020": {
            "residential_elec_kwh": r.get("conso_res_dle_elec_2020"),
            "residential_gas_kwh": r.get("conso_res_dle_gaz_2020"),
        },
    }


# --- Routes ------------------------------------------------------------------


@app.get("/v1/healthz", tags=["meta"])
async def healthz():
    return {"status": "ok", "service": "ecobuilding-api", "api_version": "v1"}


@app.get("/v1/suggest", tags=["geocoding"])
async def suggest(q: str = Query(min_length=3, description="Partial address")):
    """Address autocomplete (BAN). Returns label, BAN id and coordinates."""
    resp = await _client.get(BAN_URL, params={"q": q, "limit": 5, "type": "housenumber"})
    resp.raise_for_status()
    feats = resp.json().get("features", [])
    return {
        "suggestions": [
            {
                "label": f["properties"]["label"],
                "ban_id": f["properties"]["id"],
                "lon": f["geometry"]["coordinates"][0],
                "lat": f["geometry"]["coordinates"][1],
            }
            for f in feats
        ]
    }


@app.get("/v1/lookup", tags=["buildings"])
async def lookup(
    q: str | None = Query(None, description="Free-text address"),
    ban_id: str | None = Query(None, description="BAN interop id, e.g. 80021_6370_00007"),
    lon: float | None = Query(None, description="Longitude (used for the risk report when ban_id is given)"),
    lat: float | None = Query(None, description="Latitude (idem)"),
):
    """Address -> geocode (BAN) -> building record (BDNB) -> risk report (Géorisques)."""
    if not q and not ban_id:
        raise HTTPException(422, "Provide q or ban_id")

    address = None
    if not ban_id:
        geo = await _client.get(BAN_URL, params={"q": q, "limit": 1, "type": "housenumber"})
        geo.raise_for_status()
        feats = geo.json().get("features", [])
        if not feats:
            M_LOOKUPS.add(1, {"status": "address_not_found"})
            raise HTTPException(404, "Address not found (BAN)")
        p = feats[0]["properties"]
        ban_id, address = p["id"], p["label"]
        lon, lat = feats[0]["geometry"]["coordinates"][:2]

    bdnb = await _client.get(
        BDNB_URL, params={"cle_interop_adr": f"eq.{ban_id}", "limit": "5"}
    )
    bdnb.raise_for_status()
    rows = bdnb.json()
    if not isinstance(rows, list):
        log.warning("BDNB error: %s", rows)
        rows = []

    risks = None
    if lon is not None:
        try:
            g = await _client.get(GEORISQUES_URL, params={"latlon": f"{lon},{lat}"})
            if g.status_code == 200:
                gj = g.json()
                risks = {
                    "commune": (gj.get("commune") or {}).get("libelle"),
                    "report_url": gj.get("url"),
                    "risques_naturels": [
                        k
                        for k, v in (gj.get("risquesNaturels") or {}).items()
                        if isinstance(v, dict) and v.get("present")
                    ],
                    "risques_technologiques": [
                        k
                        for k, v in (gj.get("risquesTechnologiques") or {}).items()
                        if isinstance(v, dict) and v.get("present")
                    ],
                }
        except httpx.HTTPError as e:
            log.warning("Géorisques unavailable: %s", e)

    M_LOOKUPS.add(1, {"status": "ok" if rows else "no_building"})
    return {
        "query": {"q": q, "ban_id": ban_id, "address": address, "lon": lon, "lat": lat},
        "buildings": [_normalize_building(r) for r in rows],
        "area_risks": risks,
        "sources": [
            "BDNB (CSTB) — Licence Ouverte v2.0",
            "BAN — Licence Ouverte",
            "Géorisques — Licence Ouverte",
        ],
    }


class FrontendEvent(BaseModel):
    event: str
    meta: str | None = None


@app.post("/v1/events", tags=["telemetry"], status_code=204)
async def track(ev: FrontendEvent):
    """Anonymous frontend usage beacon (no cookies, no IP stored) -> OTel counter."""
    M_FRONTEND.add(1, {"event": ev.event[:40]})
    return None
