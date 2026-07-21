"""Normalized per-building PDF fiche (weasyprint).

Target user: diagnostiqueurs / pre-sale professionals — a consistent one-page
document to prepare a visit or a dossier. Free during beta; usage measured
via the ecobuilding_reports metric.
"""

from datetime import datetime, timezone

from weasyprint import HTML

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

<footer>
  Sources : BDNB (CSTB), Base Adresse Nationale, Géorisques — Licence Ouverte, attributions requises.
  Document informatif généré automatiquement à partir de données ouvertes : il ne remplace ni un
  diagnostic de performance énergétique (DPE) officiel, ni un état des risques et pollutions (ERP)
  réglementaire. Version bêta gratuite.
</footer>
"""
    return HTML(string=html).write_pdf()
