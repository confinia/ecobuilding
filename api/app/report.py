"""Normalized per-building PDF fiche (weasyprint).

Target user: diagnostiqueurs / pre-sale professionals — a consistent one-page
document to prepare a visit or a dossier. Free during beta; usage measured
via the ecobuilding_reports metric.
"""

from datetime import datetime, timezone

from weasyprint import HTML

DPE_COLORS = {"A": "#009036", "B": "#52b153", "C": "#a5cc74", "D": "#f4e70f",
              "E": "#f0b40f", "F": "#eb8235", "G": "#d7221f"}


def _row(label, value, unit=""):
    if value in (None, "", []):
        return ""
    return f'<tr><td class="k">{label}</td><td>{value}{unit}</td></tr>'


def build_report_pdf(data: dict) -> bytes:
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

<footer>
  Sources : BDNB (CSTB), Base Adresse Nationale, Géorisques — Licence Ouverte, attributions requises.
  Document informatif généré automatiquement à partir de données ouvertes : il ne remplace ni un
  diagnostic de performance énergétique (DPE) officiel, ni un état des risques et pollutions (ERP)
  réglementaire. Version bêta gratuite.
</footer>
"""
    return HTML(string=html).write_pdf()
