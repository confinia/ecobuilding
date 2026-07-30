"""Normalized per-building PDF fiche (weasyprint).

Target user: diagnostiqueurs / pre-sale professionals — a consistent one-page
document to prepare a visit or a dossier. Free during beta; usage measured
via the ecobuilding_reports metric.
"""

from datetime import datetime, timezone
from urllib.parse import quote

from weasyprint import HTML

# Dataset versions surfaced in the traceability annex (#93). Update on refresh.
BDNB_MILLESIME = "2026_02 (open data)"
DVF_WINDOW = "2021-2025"

DPE_COLORS = {"A": "#009036", "B": "#52b153", "C": "#a5cc74", "D": "#f4e70f",
              "E": "#f0b40f", "F": "#eb8235", "G": "#d7221f"}
GES_COLORS = {"A": "#f2eefb", "B": "#dfd3f3", "C": "#c7b2e9", "D": "#a98ddb",
              "E": "#8a68cb", "F": "#6b46b8", "G": "#4a2a94"}
# Ad-style class thresholds (kWh/m²/an and kgCO2/m²/an) to derive the GES
# class when only the value is known.
GES_BOUNDS = [(6, "A"), (11, "B"), (30, "C"), (50, "D"), (70, "E"), (100, "F")]


def _ges_class(value):
    if value is None:
        return None
    for bound, cls in GES_BOUNDS:
        if value <= bound:
            return cls
    return "G"


def _scale(active_cls, colors, value_text, dark_text_classes=("A", "B", "C", "D")):
    """Ad-style A→G arrow scale with the active class highlighted."""
    rows = []
    for i, cls in enumerate("ABCDEFG"):
        width = 30 + i * 10
        active = cls == active_cls
        text_col = "#333" if (colors is GES_COLORS and cls in dark_text_classes) or cls == "D" else "#fff"
        extra = (f'<span class="val">{value_text}</span>' if active and value_text else "")
        rows.append(
            f'<div class="bar{" active" if active else ""}" '
            f'style="width:{width}%;background:{colors[cls]};color:{text_col}">'
            f'<strong>{cls}</strong>{extra}</div>'
        )
    return '<div class="scale">' + "".join(rows) + "</div>"


def _row(label, value, unit=""):
    if value in (None, "", []):
        return ""
    return f'<tr><td class="k">{label}</td><td>{value}{unit}</td></tr>'


def _eur(n) -> str:
    return f"{round(n):,}".replace(",", " ") if n not in (None, "") else "—"


def _prices_html(p: dict | None) -> str:
    """DVF home-price section (recent parcelle sales + commune median €/m²).
    Honest about the DVF coverage gap (Alsace-Moselle, Mayotte)."""
    if not p:
        return ""
    if not p.get("available"):
        return ('<h2>Prix de vente (DVF)</h2><p class="meta">Données de prix indisponibles pour '
                "ce secteur : la base DVF ne couvre pas l'Alsace-Moselle ni Mayotte.</p>")
    med = {t: v for t, v in (p.get("commune_eur_m2") or {}).items() if v.get("median")}
    med_txt = " · ".join(f"{t} {_eur(v['median'])} €/m² (n={v['n']})" for t, v in med.items()) or "—"
    rows = ""
    for s in (p.get("sales") or [])[:6]:
        surf = f"{round(s['surface_m2'])} m²" if s.get("surface_m2") else "—"
        em = f"{_eur(s['eur_m2'])} €/m²" if s.get("eur_m2") else "—"
        rows += (f'<tr><td>{(s.get("date") or "")[:10]}</td><td>{s.get("type_local") or "—"}</td>'
                 f'<td>{surf}</td><td>{_eur(s.get("valeur_fonciere"))} €</td><td>{em}</td></tr>')
    sales_tbl = (f'<table><tr><td class="k">Date</td><td class="k">Type</td><td class="k">Surface</td>'
                 f'<td class="k">Montant</td><td class="k">€/m²</td></tr>{rows}</table>'
                 if rows else '<p class="meta">Aucune vente récente enregistrée sur la parcelle.</p>')
    return (f'<h2>Prix de vente (DVF)</h2>'
            f'<p>Prix médian dans la commune : <strong>{med_txt}</strong></p>{sales_tbl}'
            f'<p class="meta">€/m² indicatif, calculé sur les ventes d\'un seul local. '
            f'Transactions réelles enregistrées par la DGFiP.</p>')


def _prov(source, version, key, date, link_url) -> str:
    """One provenance card. Empty rows are omitted; the verify link is real
    (never fabricated) — a URL only when we actually have a reproducible one."""
    link = f'<a href="{link_url}">{link_url}</a>' if link_url and link_url != "—" else "—"
    rows = "".join(_row(k, v) for k, v in [
        ("Source", source), ("Version / licence", version),
        ("Clé de recherche", key), ("Date de référence", date),
        ("Vérifier à la source", link)])
    return f"<table>{rows}</table>" if rows else ""


def _traceability_annex(data: dict, photos: list | None) -> str:
    """Annex page (#93): for each datum, its source, version, the exact key used
    to fetch it, a reference date and a verifiable upstream link — so the reader
    checks against the origin instead of trusting EcoBuilding. Only categories
    actually present are listed; no empty rows, no fake links."""
    b = (data.get("buildings") or [{}])[0]
    q = data.get("query", {})
    e = b.get("energy") or {}
    risks = data.get("area_risks") or {}
    prices = data.get("prices") or {}
    photos = [p for p in (photos or []) if p.get("id")]
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    bdnb_id = b.get("bdnb_id") or q.get("bdnb_id")
    lon, lat = q.get("lon"), q.get("lat")
    commune = risks.get("commune") or prices.get("commune_code")
    addr = q.get("address") or b.get("address")

    cards = []
    if addr:
        key = addr + (f" · id BAN {q['ban_id']}" if q.get("ban_id") else "")
        cards.append(("Adresse", _prov(
            "Base Adresse Nationale (BAN)", "Licence Ouverte",
            key, "Référentiel courant",
            f"https://api-adresse.data.gouv.fr/search/?q={quote(addr)}")))
    if bdnb_id:
        cards.append(("Bâtiment, énergie (DPE), solaire", _prov(
            "BDNB — Base de Données Nationale des Bâtiments (CSTB)",
            f"Millésime {BDNB_MILLESIME} · Licence Ouverte 2.0",
            f"batiment_groupe_id = {bdnb_id}",
            ((e.get("dpe_date") or "")[:10] + " (date du DPE)")
            if e.get("dpe_date") else f"Millésime {BDNB_MILLESIME}",
            "https://api.bdnb.io/v1/bdnb/donnees/batiment_groupe_complet"
            f"?batiment_groupe_id=eq.{bdnb_id}")))
    if risks.get("report_url") or lon is not None:
        key = ((f"lat/lon = {lat}, {lon}" if lon is not None else "")
               + (f" · commune INSEE {commune}" if commune else "")) or "—"
        cards.append(("Risques", _prov(
            "Géorisques (BRGM / Ministère de la Transition écologique)",
            "Licence Ouverte", key, f"Consultation du {now}",
            risks.get("report_url") or "https://www.georisques.gouv.fr")))
    if prices:
        if prices.get("available"):
            yrs = sorted(s["date"][:4] for s in (prices.get("sales") or []) if s.get("date"))
            dref = (f"ventes {yrs[0]}–{yrs[-1]}" if yrs else f"fenêtre {DVF_WINDOW}")
            cards.append(("Prix (DVF)", _prov(
                "DVF géolocalisé — Demandes de Valeurs Foncières (DGFiP / Etalab)",
                f"Fenêtre {DVF_WINDOW} · Licence Ouverte 2.0",
                f"parcelle cadastrale du bâtiment · commune INSEE {prices.get('commune_code') or '—'}",
                dref, "https://app.dvf.etalab.gouv.fr")))
        else:
            cards.append(("Prix (DVF)", _prov(
                "DVF (DGFiP / Etalab)", f"Fenêtre {DVF_WINDOW} · Licence Ouverte 2.0",
                "indisponible : l'Alsace-Moselle et Mayotte ne sont pas couvertes par la DVF",
                "—", "https://app.dvf.etalab.gouv.fr")))
    if photos:
        ids = ", ".join(str(p["id"])[:8] for p in photos[:3])
        dref = next((str(p["date"])[:10] for p in photos if p.get("date")), "voir la visionneuse")
        cards.append(("Photos (contexte)", _prov(
            "Panoramax", "CC-BY-SA 4.0", f"photo id(s) : {ids}", dref,
            photos[0].get("viewer") or "https://panoramax.xyz")))

    sections = "".join(f"<h2>{t}</h2>{c}" for t, c in cards if c)
    if not sections:
        return ""
    return f"""
<div style="page-break-before: always;"></div>
<header>
  <div class="brand">EcoBuilding</div>
  <div class="doctitle">Annexe — traçabilité des données</div>
</header>
<h1>D'où vient chaque donnée</h1>
<p class="meta">Ce rapport agrège des données ouvertes. Pour chaque donnée : la source,
la version, la clé de recherche exacte et un lien pour vérifier directement à la source,
sans avoir à faire confiance à EcoBuilding. Généré le {now}.</p>
{sections}
<footer>
  Sources publiques (Licence Ouverte, CC-BY-SA, ODbL). Les identifiants ci-dessus
  permettent de retrouver la donnée d'origine. Document informatif, non contractuel.
</footer>
"""


def build_report_pdf(data: dict, photos: list | None = None) -> bytes:
    b = (data.get("buildings") or [{}])[0]
    e = b.get("energy") or {}
    ban = e.get("rental_ban") or {}
    risks = data.get("area_risks") or {}
    solar = b.get("solar") or {}
    cls = (e.get("dpe_class") or "?").upper()
    color = DPE_COLORS.get(cls, "#999")
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    address = data.get("query", {}).get("address") or b.get("address") or "Adresse inconnue"

    ban_html = ""
    if e.get("dpe_class"):
        if ban.get("rental_ban_date"):
            ban_html = (f'<div class="ban warn">⚠ Location interdite à partir du '
                        f'<strong>{ban["rental_ban_date"][:4]}</strong> (loi Climat &amp; Résilience)</div>')
        else:
            ban_html = '<div class="ban ok">Aucune interdiction de location prévue pour cette classe</div>'

    zone_risks = ", ".join((risks.get("risques_naturels") or []) + (risks.get("risques_technologiques") or [])) or None
    conso = e.get("consumption_kwh_m2y")
    ges = e.get("ghg_kgco2_m2y")

    html = f"""
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  body {{ font-family: 'DejaVu Sans', sans-serif; font-size: 10.5pt; color: #222; }}
  header {{ border-bottom: 2px solid #2b7a4b; padding-bottom: 6px; margin-bottom: 14px; }}
  .brand {{ font-size: 14pt; font-weight: bold; color: #2b7a4b; }}
  .doctitle {{ font-size: 11pt; color: #555; }}
  h1 {{ font-size: 13pt; margin: 10px 0 2px; }}
  .meta {{ font-size: 8.5pt; color: #777; }}
  .dpe {{ display: inline-block; min-width: 26pt; text-align: center; font-weight: bold;
         color: #fff; background: {color}; border-radius: 4pt; padding: 4pt 8pt; font-size: 15pt; }}
  {'.dpe { color: #333; }' if cls == 'D' else ''}
  .ban {{ margin: 6pt 0; padding: 6pt 8pt; border-radius: 4pt; font-size: 10pt; }}
  .ban.warn {{ background: #fdecea; color: #b3261e; }}
  .ban.ok {{ background: #e8f5e9; color: #2b7a4b; }}
  h2 {{ font-size: 10pt; text-transform: uppercase; letter-spacing: .05em; color: #2b7a4b;
       border-bottom: 1px solid #ddd; padding-bottom: 2pt; margin: 14pt 0 6pt; }}
  table {{ width: 100%; border-collapse: collapse; }}
  td {{ padding: 3pt 4pt; border-bottom: 0.5pt dashed #eee; vertical-align: top; }}
  td.k {{ color: #666; width: 45%; }}
  footer {{ margin-top: 18pt; font-size: 7.5pt; color: #888; border-top: 0.5pt solid #ccc; padding-top: 6pt; }}
  .labels {{ margin: 8pt 0 2pt; }}
  .labels td {{ width: 50%; border: none; padding: 0 8pt 0 0; }}
  .lbl-title {{ font-size: 8.5pt; font-weight: bold; margin-bottom: 3pt; }}
  .lbl-title span {{ font-weight: normal; color: #777; }}
  .scale .bar {{ padding: 2.2pt 5pt; margin: 1.2pt 0; border-radius: 0 3pt 3pt 0; font-size: 8.5pt; }}
  .scale .bar strong {{ font-size: 9.5pt; }}
  .scale .bar.active {{ outline: 1.5pt solid #333; font-size: 10pt; }}
  .scale .bar .val {{ float: right; font-weight: bold; }}
</style>
<header>
  <div class="brand">EcoBuilding</div>
  <div class="doctitle">Fiche bâtiment normalisée — données ouvertes</div>
</header>
<h1>{address}</h1>
<p class="meta">Identifiant BDNB : {b.get("bdnb_id") or "—"} · Générée le {now} · ecobuilding.confinia.io</p>

<h2>Énergie (DPE)</h2>
<p><span class="dpe">{cls}</span>&nbsp;&nbsp;{f"{round(conso)} kWh/m²/an" if conso else "Aucun DPE enregistré dans la BDNB pour ce bâtiment"}</p>
{ban_html}
{('<table class="labels"><tr>'
  '<td><div class="lbl-title">Étiquette énergie <span>(kWh/m²/an, énergie primaire)</span></div>'
  + _scale(cls, DPE_COLORS, f"{round(conso)}" if conso else "") +
  '</td><td><div class="lbl-title">Étiquette climat <span>(kgCO₂/m²/an)</span></div>'
  + _scale(_ges_class(ges), GES_COLORS, f"{round(ges)}" if ges else "") +
  '</td></tr></table>') if e.get("dpe_class") else ""}
<table>
  {_row("Date du DPE", (e.get("dpe_date") or "")[:10] or None)}
  {_row("Émissions GES", round(ges) if ges else None, " kgCO₂/m²/an")}
</table>

<h2>Bâtiment</h2>
<table>
  {_row("Année de construction", b.get("construction_year"))}
  {_row("Hauteur moyenne", b.get("height_m"), " m")}
  {_row("Logements", b.get("dwellings"))}
  {_row("Matériaux des murs", b.get("wall_material"))}
  {_row("Matériaux du toit", b.get("roof_material"))}
</table>

<h2>Risques</h2>
<table>
  {_row("Retrait-gonflement des argiles", (b.get("risks") or {}).get("clay_shrink_swell"))}
  {_row("Risques recensés dans la zone", zone_risks)}
  {_row("Rapport Géorisques", risks.get("report_url"))}
</table>

<h2>Solaire</h2>
<table>
  {_row("Favorable au solaire thermique", {True: "oui", False: "non"}.get(solar.get("thermal_favourable")))}
  {_row("Potentiel annuel estimé", solar.get("thermal_potential_kwh_y"), " kWh/an")}
</table>

{_prices_html(data.get("prices"))}

<footer>
  Sources : BDNB (CSTB), Base Adresse Nationale, Géorisques — Licence Ouverte, attributions requises.
  Document informatif généré automatiquement à partir de données ouvertes : il ne remplace ni un
  diagnostic de performance énergétique (DPE) officiel, ni un état des risques et pollutions (ERP)
  réglementaire. Version bêta gratuite.
</footer>
{_context_page(data, photos)}
{_traceability_annex(data, photos)}
"""
    return HTML(string=html).write_pdf()


def _context_page(data: dict, photos: list | None) -> str:
    """Second PDF page: third-party context (Panoramax imagery + OSM link)."""
    q = data.get("query", {})
    lon, lat = q.get("lon"), q.get("lat")
    address = q.get("address") or "ce bâtiment"
    photos = photos or []
    def _pic(p):
        src = p.get("sd") or p.get("thumb")
        # 360° photospheres are equirectangular and warp on flat paper: crop to
        # a forward-facing central window (~90°x45°) instead of the full strip.
        # Non-360 photos are shown as-is. (True rectilinear reprojection = #81.)
        if p.get("is_360"):
            inner = f'<div class="crop"><img src="{src}"/></div>'
        else:
            inner = f'<img class="flat" src="{src}"/>'
        return f'<div class="pic">{inner}<div class="cap">Panoramax — CC-BY-SA</div></div>'

    pics = "".join(_pic(p) for p in photos[:2] if p.get("sd") or p.get("thumb"))
    if not pics and lon is None:
        return ""
    osm = (f'<a href="https://www.openstreetmap.org/#map=19/{lat}/{lon}">'
           f'openstreetmap.org (19/{lat}/{lon})</a>' if lon is not None else "—")
    return f"""
<div style="page-break-before: always;"></div>
<header>
  <div class="brand">EcoBuilding</div>
  <div class="doctitle">Contexte — sources tierces</div>
</header>
<h1>{address}</h1>
<h2>Vue au sol (Panoramax)</h2>
{('<div class="pics">' + pics + '</div>') if pics else '<p class="meta">Aucune photo Panoramax à proximité.</p>'}
<h2>OpenStreetMap</h2>
<table><tr><td class="k" style="width:30%">Voir la zone sur OSM</td><td>{osm}</td></tr></table>
<footer>
  Imagerie : Panoramax (CC-BY-SA 4.0). Cartographie : OpenStreetMap et contributeurs (ODbL).
  Informations de contexte, non contractuelles.
</footer>
<style>
  .pics {{ display: flex; gap: 8pt; flex-wrap: wrap; }}
  .pic img.flat {{ width: 240pt; border-radius: 4pt; }}
  /* Central forward crop of an equirectangular 360 (2:1 image): box shows the
     central 1/4 width (90 deg) x 1/4 height (45 deg). */
  .pic .crop {{ width: 240pt; height: 120pt; overflow: hidden; border-radius: 4pt; }}
  .pic .crop img {{ width: 960pt; margin-left: -360pt; margin-top: -180pt; }}
  .pic .cap {{ font-size: 7pt; color: #888; }}
</style>"""
