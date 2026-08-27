"""Normalized per-building PDF fiche (weasyprint).

Target user: diagnostiqueurs / pre-sale professionals — a consistent one-page
document to prepare a visit or a dossier. Usage measured
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


def _dia_html(m):
    """Bloc « Dynamique du marché (DIA) » — uniquement sur le territoire de
    Montpellier Méditerranée Métropole. Le libellé dit explicitement qu'il
    s'agit de montants DEMANDÉS (mise en vente), pas de prix finaux."""
    if not m:
        return ""
    vol = f"{m['listings_12m']}"
    if m.get("listings_3m"):
        vol += f" — dont {m['listings_3m']} au dernier trimestre"
    price = ""
    if m.get("median_asking_eur"):
        price = f"{m['median_asking_eur']:,} €".replace(",", " ")
        if m.get("median_asking_eur_m2"):
            price += f" ({m['median_asking_eur_m2']:,} €/m²)".replace(",", " ")
    return f"""
<h2>Dynamique du marché (DIA)</h2>
<table>
  {_row("Zone", f"{m['zone']} ({m['scope']})")}
  {_row("Mises en vente sur 12 mois", vol)}
  {_row("Prix médian demandé", price or None)}
</table>
<p class="note">{m['note']} Données {m['updated']} —
Montpellier Méditerranée Métropole (Open Data).</p>
"""


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
    sales_tbl = (f'<table class="sales"><tr><td class="k">Date</td><td class="k">Type</td><td class="k">Surface</td>'
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
    return f'<table class="prov">{rows}</table>' if rows else ""


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
        # Deep-link straight to the property on the official DVF explorer (#98):
        # verified that explore.data.gouv.fr/immobilier reads lat/lng/zoom and
        # centres the map there. Fall back to the app home if we lack coords.
        dvf_url = (f"https://explore.data.gouv.fr/fr/immobilier?onglet=carte&lat={lat}&lng={lon}&zoom=18"
                   if (lon is not None and lat is not None) else "https://app.dvf.etalab.gouv.fr")
        if prices.get("available"):
            yrs = sorted(s["date"][:4] for s in (prices.get("sales") or []) if s.get("date"))
            dref = (f"ventes {yrs[0]}–{yrs[-1]}" if yrs else f"fenêtre {DVF_WINDOW}")
            cards.append(("Prix (DVF)", _prov(
                "DVF géolocalisé — Demandes de Valeurs Foncières (DGFiP / Etalab)",
                f"Fenêtre {DVF_WINDOW} · Licence Ouverte 2.0",
                f"parcelle cadastrale du bâtiment · commune INSEE {prices.get('commune_code') or '—'}",
                dref, dvf_url)))
        else:
            cards.append(("Prix (DVF)", _prov(
                "DVF (DGFiP / Etalab)", f"Fenêtre {DVF_WINDOW} · Licence Ouverte 2.0",
                "indisponible : l'Alsace-Moselle et Mayotte ne sont pas couvertes par la DVF",
                "—", dvf_url)))
    od = data.get("official_dpe") or {}
    if od.get("dpe_number"):
        cards.append(("DPE officiel", _prov(
            "Observatoire DPE (ADEME)", "Licence Ouverte",
            f"numero_dpe = {od['dpe_number']} (logement représentatif BDNB)",
            od.get("established_on") or "—",
            "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
            f"?qs=numero_dpe:%22{od['dpe_number']}%22")))
    lt = data.get("local_taxes") or {}
    if lt.get("property_tax_built_pct") is not None:
        cards.append(("Fiscalité locale", _prov(
            "DGFiP — Fiscalité directe locale (data.economie.gouv.fr)",
            "Licence Ouverte", f"insee_com = {commune or '—'} · exercice {lt.get('year') or '—'}",
            f"exercice {lt.get('year') or '—'}",
            "https://data.economie.gouv.fr/explore/dataset/fiscalite-locale-des-particuliers-geo/")))
    sc = data.get("schools") or {}
    if sc.get("within_2km"):
        cards.append(("Écoles", _prov(
            "Annuaire de l'éducation (MENJ)", "Licence Ouverte",
            f"within_distance 2 km de {lat}, {lon}", "annuaire courant",
            "https://data.education.gouv.fr/explore/dataset/fr-en-annuaire-education/")))
    gw = data.get("groundwater") or {}
    if gw.get("available"):
        cards.append(("Eau souterraine (nappe)", _prov(
            "Hub'Eau piézométrie — ADES (BRGM / OFB)", "Licence Ouverte",
            f"code BSS {gw.get('station_code_bss')} · station à {gw.get('station_distance_m')} m du bâtiment",
            (gw.get("measured_on") or "—")[:10] + " (dernière mesure)",
            "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/chroniques"
            f"?code_bss={quote(gw.get('station_code_bss') or '')}&size=1&sort=desc")))
    wn = data.get("water_network") or {}
    if wn.get("efficiency_pct") is not None:
        cards.append(("Eau potable (rendement du réseau)", _prov(
            "SISPEA — Observatoire des services publics d'eau (OFB)",
            "Licence Ouverte",
            f"commune INSEE {wn.get('commune_insee') or '—'} · indicateur P104.3",
            f"année {wn.get('year') or '—'} (dernière publiée)",
            "https://hubeau.eaufrance.fr/api/v0/indicateurs_services/communes"
            f"?code_commune={wn.get('commune_insee') or ''}&type_service=AEP")))
    pv = data.get("solar_pv") or {}
    if pv and lon is not None:
        cards.append(("Solaire photovoltaïque", _prov(
            "PVGIS v5.2 (Joint Research Centre, Commission européenne)",
            "© Union européenne", f"lat/lon = {lat}, {lon} · {pv.get('assumptions') or ''}",
            "base climatique PVGIS-SARAH2",
            f"https://re.jrc.ec.europa.eu/api/v5_2/PVcalc?lat={lat}&lon={lon}"
            "&peakpower=1&loss=14&optimalinclination=1&outputformat=json")))
    if photos:
        ids = ", ".join(str(p["id"])[:8] for p in photos[:3])
        dref = next((str(p["date"])[:10] for p in photos if p.get("date")), "voir la visionneuse")
        srcs = sorted({p.get("source", "Panoramax") for p in photos[:4]})
        cards.append(("Photos (contexte)", _prov(
            " et ".join(srcs), "CC-BY-SA / licences libres, voir chaque image",
            f"photo id(s) : {ids}", dref,
            photos[0].get("viewer") or "https://panoramax.xyz")))

    sections = "".join(f"<h2>{t}</h2>{c}" for t, c in cards if c)
    if not sections:
        return ""
    return f"""
<style>
  table.prov {{ table-layout: fixed; }}
  table.prov td {{ overflow-wrap: anywhere; word-break: break-word; }}
  table.prov td.k {{ width: 26%; }}
  table.prov a {{ word-break: break-all; }}
</style>
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


def _principal_address_note(shown_address: str, b: dict) -> str:
    """When the fiche is titled with the searched address but the BDNB
    'bâtiment groupe' has a different principal address (a group can span
    several streets, #146), say so instead of silently looking wrong."""
    principal = b.get("address")
    if not principal or principal == shown_address:
        return ""
    n = f" ({b['dwellings']} logements)" if b.get("dwellings") else ""
    return (f'<p class="meta">Bâtiment groupe BDNB{n} — '
            f'adresse principale : {principal}</p>')


def _dpe_spread_html(e: dict, dpe_representatif: str | None = None) -> str:
    """L'éventail des DPE connus à l'adresse (#287).

    Une classe unique par bâtiment se trompe pour presque tous les logements
    dès qu'un immeuble en compte plusieurs — mesuré : deux fois sur trois les
    classes diffèrent. La fiche remise à un acheteur ne peut pas porter cette
    approximation sans la nommer.

    Vide s'il n'y a qu'un diagnostic : la fiche a déjà raison dans ce cas.
    """
    if not e or not e.get("diagnostics"):
        return ""
    parts = " · ".join(f"{c} : {n}" for c, n in (e.get("repartition") or {}).items())
    titre = (f"{e['diagnostics']} diagnostics connus à cette adresse, "
             f"tous en {e['classe_min']}."
             if e.get("identiques") else
             f"{e['diagnostics']} diagnostics connus à cette adresse : "
             f"de {e['classe_min']} à {e['classe_max']}.")
    couv = (f" L'immeuble compte {e['logements_batiment']} logements."
            if e.get("logements_batiment") else "")
    # La liste des logements, pour que le lecteur RECONNAISSE le sien.
    #
    # On ne prétend pas désigner son lot — le DPE ne porte ni numéro de lot ni
    # étage fiable. On lui donne les deux clés qu'il possède : sa surface, lue
    # sur l'annonce, et le numéro de DPE que le vendeur lui remet
    # obligatoirement. Et on dit, LIGNE PAR LIGNE, quand la surface ne tranche
    # pas — ce qui n'arrive que dans un cas sur cinq.
    # UN BLOC PAR DPE.
    #
    # Un tableau suivi des caractéristiques détaillées d'un seul logement se
    # lisait comme « trois diagnostics, une seule date ». Chaque diagnostic a
    # sa date, sa consommation, son coût et son isolation : il lui faut son
    # bloc.
    blocs = []
    for l in (e.get("logements") or []):
        m2 = l.get("surface_m2")
        est_repr = bool(dpe_representatif and l.get("numero_dpe") == dpe_representatif)
        isolation = " · ".join(x for x in (
            f"enveloppe {l['isolation_enveloppe']}" if l.get("isolation_enveloppe") else "",
            f"menuiseries {l['isolation_menuiseries']}" if l.get("isolation_menuiseries") else "",
        ) if x)
        marque = ("seul logement de cette surface" if l.get("identifiable")
                  else f"{l.get('memes_surfaces')} logements de cette surface — indiscernables")
        titre = (f"{m2} m²" if m2 is not None else "Logement")
        blocs.append(
            f'<div class="logement{" repr" if est_repr else ""}">'
            f'<div class="logement-t"><strong>{titre} — classe {l.get("classe")}</strong>'
            f'{" · classe affichée ci-dessus" if est_repr else ""}</div>'
            "<table>"
            + _row("Établi le", l.get("etabli_le"))
            + _row("Consommation", l.get("conso_kwh_m2y") and round(l["conso_kwh_m2y"]), " kWh/m²/an")
            + _row("GES", l.get("ges_kgco2_m2y") and round(l["ges_kgco2_m2y"]), " kgCO₂/m²/an")
            + _row("Coût annuel", _eur(l["cout_annuel_eur"]) + " €/an" if l.get("cout_annuel_eur") else None)
            + _row("Isolation", isolation or None)
            + _row("N° DPE", l.get("numero_dpe"))
            + "</table>"
            + f'<p class="meta">{marque}</p></div>')
    table = ""
    if blocs:
        table = "".join(blocs) + """
<p class="meta">Retrouvez le logement concerné par sa surface, ou par le numéro
de DPE que le vendeur remet obligatoirement — il est vérifiable sur
l'observatoire de l'ADEME.</p>"""
    return f"""
<div class="ban">{titre} La classe ci-dessus est celle du logement
représentatif du bâtiment, pas celle de tous.{couv}</div>
<p class="meta">Répartition — {parts}. Source : ADEME, observatoire DPE.
Seuls les logements diagnostiqués figurent : c'est un minimum observé, pas un
inventaire de l'immeuble.</p>{table}"""


def _local_taxes_html(t: dict) -> str:
    """Recurring local taxes (#193) — the other cost sheet buyers budget."""
    if not t:
        return ""
    yr = f" ({t['year']})" if t.get("year") else ""
    return f"""
<h2>Fiscalité locale{yr}</h2>
<table>
  {_row("Taxe foncière (bâti), taux global", t.get("property_tax_built_pct"), " %")}
  {_row("Taxe ordures ménagères (TEOM)", t.get("waste_tax_pct"), " %")}
  {_row("Taxe foncière (non bâti)", t.get("property_tax_unbuilt_pct"), " %")}
  {_row("Intercommunalité", t.get("intercommunalite"))}
</table>
<p class="meta">Taux globaux (commune + intercommunalité + syndicats), dernier exercice
publié (DGFiP). La taxe due dépend de la valeur locative cadastrale du bien.</p>"""


def _commune_html(c: dict) -> str:
    """La commune au sens civil, et le nom qu'elle portait avant (#275).

    Un acte ancien nomme parfois une commune qui n'existe plus. Et quand rien
    n'a bougé, le dire — daté et sourcé — vaut aussi la peine.

    Les réserves de la source sont reprises telles quelles : reprendre ses
    chiffres sans ses réserves affirmerait plus qu'elle ne le fait.
    """
    if not c or not c.get("nom"):
        return ""
    avant = (_row("Auparavant",
                  f"{c['precedent']['nom']}, jusqu'au {c['precedent']['jusqu_au_fr']}")
             if c.get("precedent") else "")
    reserves = list(c.get("limites") or []) + [
        d.get("texte") for d in (c.get("non_etablis") or []) if d.get("texte")]
    credits = " ; ".join(
        f"{a.get('attribution')} ({a.get('license')})"
        for a in (c.get("attribution") or []) if a.get("attribution"))
    return f"""
<h2>Commune</h2>
<table>
  {_row("Commune", f"{c['nom']} ({c['code']})")}
  {_row("Nom et limites inchangés depuis", c.get("depuis_fr"))
    if c.get("existe_encore") else
    _row("A cessé d'exister le", c.get("jusqu_au_fr"))}
  {avant}
  {_row("Données arrêtées au", c.get("arret_des_donnees_fr"))}
</table>
{f'<p class="meta">{" ".join(reserves)}</p>' if reserves else ""}
{f'<p class="meta">Source : {credits}.</p>' if credits else ""}"""


def _schools_html(sc: dict) -> str:
    """Nearest schools (#194) — proximity, NOT the carte scolaire."""
    if not sc:
        return ""
    rows = "".join(
        _row(f"{s.get('type') or 'Établissement'} · {s.get('statut') or ''}".strip(" ·"),
             f"{s.get('name')} ({s.get('distance_m')} m)")
        for s in (sc.get("nearest") or []))
    if not rows:
        return ('<h2>Écoles à proximité</h2><p class="meta">Aucun établissement recensé '
                'à moins de 2 km (annuaire de l\'éducation).</p>')
    return f"""
<h2>Écoles à proximité ({sc.get('within_2km')} à moins de 2 km)</h2>
<table>{rows}</table>
<p class="meta">Distances à vol d'oiseau (annuaire de l'éducation). La proximité ne vaut
pas sectorisation: la carte scolaire dépend de la commune.</p>"""


def _official_dpe_html(od: dict) -> str:
    """Official-DPE substance (#189): the fiche carries what the legal document
    carries — number, validity, surface, ANNUAL € COSTS, insulation quality,
    systems — honestly framed as the group's representative dwelling."""
    if not od or not od.get("dpe_number"):
        return ""
    ins = od.get("insulation") or {}
    cost = od.get("annual_cost_eur")
    cost_txt = (_eur(cost) + " €/an") if cost else None
    return f"""
<h2>DPE officiel (logement représentatif)</h2>
<table>
  {_row("N° DPE (ADEME)", od.get("dpe_number"))}
  {_row("Établi le", od.get("established_on"))}
  {_row("Valable jusqu'au", od.get("valid_until"), " (validité légale: 10 ans)")}
  {_row("Surface habitable", od.get("surface_habitable_m2"), " m²")}
  {_row("Coût annuel d'énergie estimé", cost_txt)}
  {_row("Chauffage", od.get("heating"))}
  {_row("Eau chaude sanitaire", od.get("hot_water"))}
  {_row("Énergies", " + ".join(od.get("energies") or []) or None)}
  {_row("Isolation: enveloppe", ins.get("enveloppe"))}
  {_row("Isolation: menuiseries", ins.get("menuiseries"))}
  {_row("Isolation: plancher bas", ins.get("plancher_bas"))}
  {_row("Isolation: plancher haut", ins.get("plancher_haut"))}
</table>
<p class="meta">Données du DPE officiel du logement représentatif du bâtiment (Observatoire
DPE, ADEME). Dans un immeuble, les autres logements peuvent différer. Coûts estimés
aux prix de l'énergie en vigueur à la date du diagnostic.</p>"""


def _water_network_html(wn: dict) -> str:
    """Commune drinking-water rows (#171): rendement du réseau + prix."""
    if not wn:
        return ""
    yr = f" ({wn['year']})" if wn.get("year") else ""
    return f"""
<h2>Eau potable (commune)</h2>
<table>
  {_row("Rendement du réseau" + yr, wn.get("efficiency_pct"), " %")}
  {_row("Part perdue en fuites", wn.get("losses_pct"), " %")}
  {_row("Prix de l'eau (120 m³)", wn.get("price_eur_m3"), " €/m³")}
</table>
<p class="meta">Indicateurs du service public d'eau potable de la commune (SISPEA / OFB),
dernière année publiée. Un rendement de 70 % signifie que 30 % de l'eau potable
produite est perdue avant d'arriver au robinet.</p>"""


def _groundwater_html(gw: dict) -> str:
    """Water-table section (#119). Honest-data: measurement is at the nearest
    piezometer, never presented as on-parcel; absent block -> no section."""
    if not gw:
        return ""
    if not gw.get("available"):
        return f'<h2>Eau souterraine</h2><p class="meta">{gw.get("note") or "Donnée indisponible."}</p>'
    station = gw.get("station_code_bss") or "—"
    if gw.get("station_commune"):
        station += f" ({gw['station_commune']})"
    dist = gw.get("station_distance_m")
    return f"""
<h2>Eau souterraine</h2>
<table>
  {_row("Profondeur de la nappe", gw.get("water_table_depth_m"), " m sous le sol")}
  {_row("Niveau piézométrique", gw.get("level_masl"), " m NGF")}
  {_row("Mesuré le", (gw.get("measured_on") or "")[:10] or None)}
  {_row("Piézomètre le plus proche", station)}
  {_row("Distance du bâtiment", dist, " m")}
</table>
<p class="meta">{gw.get("note") or ""} {gw.get("well_regulation") or ""}</p>"""


def build_report_pdf(data: dict, photos: list | None = None, map_img: str | None = None,
                     aerial_img: str | None = None, aerial_parcels: str | None = None,
                     aerial_outline: str | None = None) -> bytes:
    return HTML(string=_report_html(data, photos, map_img, aerial_img,
                                    aerial_parcels, aerial_outline)).write_pdf()


def _report_html(data: dict, photos: list | None = None, map_img: str | None = None,
                 aerial_img: str | None = None, aerial_parcels: str | None = None,
                 aerial_outline: str | None = None) -> str:
    b = (data.get("buildings") or [{}])[0]
    e = b.get("energy") or {}
    ban = e.get("rental_ban") or {}
    risks = data.get("area_risks") or {}
    solar = b.get("solar") or {}
    gw = data.get("groundwater") or {}
    pv = data.get("solar_pv") or {}
    cls = (e.get("dpe_class") or "?").upper()
    color = DPE_COLORS.get(cls, "#999")
    # Le badge dit l'EVENTAIL quand les logements de l'immeuble different
    # (#287). Une lettre unique est l'element le plus visible du document, et
    # elle a l'air categorique : mesure, elle est fausse deux fois sur trois
    # des qu'un immeuble porte plusieurs diagnostics. Le degrade va de la
    # couleur de la meilleure classe a celle de la pire.
    spread = data.get("dpe_spread") or {}
    eventail = bool(not spread.get("identiques")
                    and spread.get("classe_min") and spread.get("classe_max"))
    if eventail:
        c1 = DPE_COLORS.get(spread["classe_min"], "#999")
        c2 = DPE_COLORS.get(spread["classe_max"], "#999")
        badge = ('<span class="dpe" style="background:linear-gradient(100deg,'
                 + c1 + ' 0%,' + c2 + ' 100%);padding-left:10px;'
                 'padding-right:10px">'
                 + spread["classe_min"] + '&nbsp;-&nbsp;' + spread["classe_max"]
                 + '</span>')
    else:
        badge = '<span class="dpe">' + cls + '</span>'
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    address = data.get("query", {}).get("address") or b.get("address") or "Adresse inconnue"

    ban_html = ""
    if e.get("dpe_class"):
        if ban.get("rental_ban_date"):
            ban_html = (f'<div class="ban warn">⚠ Location interdite à partir de '
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
    .logement {{ border: 1pt solid #e0e0e0; border-radius: 5pt; padding: 5pt 7pt;
    margin: 5pt 0; break-inside: avoid; }}
  .logement.repr {{ border-color: #2b7a4b; background: #f5faf7; }}
  .logement-t {{ font-size: 9.5pt; margin-bottom: 2pt; }}
  .logement table {{ margin: 0; }}
.ban {{ margin: 6pt 0; padding: 6pt 8pt; border-radius: 4pt; font-size: 10pt; }}
  .ban.warn {{ background: #fdecea; color: #b3261e; }}
  .ban.ok {{ background: #e8f5e9; color: #2b7a4b; }}
  h2 {{ font-size: 10pt; text-transform: uppercase; letter-spacing: .05em; color: #2b7a4b;
       border-bottom: 1px solid #ddd; padding-bottom: 2pt; margin: 14pt 0 6pt;
       /* Un titre ne reste JAMAIS seul en bas de page. « Photos du lieu »
          s'affichait suivi d'un grand blanc, son contenu rejeté à la page
          suivante : le lecteur en concluait que la fiche était incomplète,
          alors que les photos étaient là, une page plus loin. */
       break-after: avoid; page-break-after: avoid; }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
  td {{ padding: 3pt 4pt; border-bottom: 0.5pt dashed #eee; vertical-align: top;
       overflow-wrap: anywhere; word-break: break-word; }}
  td.k {{ color: #666; width: 45%; }}
  /* Multi-column tables: the 45% key width is per-cell and would overflow a
     fixed layout — let the auto algorithm size them. */
  table.sales {{ table-layout: auto; }}
  table.sales td.k {{ width: auto; }}
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
  <!-- « normalisée » promettait une norme qui n'existe pas : ce document est
       assemblé à partir de données ouvertes, il ne se conforme à aucun
       référentiel. Dire ce qu'il EST — formaté par nous, sourcé chez l'État —
       vaut mieux que d'emprunter l'autorité d'une norme. -->
  <div class="doctitle">Fiche bâtiment formatée et sourcée — données ouvertes</div>
</header>
<h1>{address}</h1>
{_principal_address_note(address, b)}
<p class="meta">Identifiant BDNB : {b.get("bdnb_id") or "—"} · Générée le {now} · ecobuilding.confinia.io</p>

<h2>Énergie (DPE)</h2>
<p>{badge}&nbsp;&nbsp;{f"{round(conso)} kWh/m²/an" if conso else "Aucun DPE enregistré dans la BDNB pour ce bâtiment"}</p>
{ban_html}
{_dpe_spread_html(data.get("dpe_spread") or {}, (data.get("official_dpe") or {}).get("dpe_number"))}
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
{_official_dpe_html(data.get("official_dpe") or {})}

<h2>Bâtiment</h2>
<table>
  {_row("ID-RNB (référentiel national)", b.get("rnb_id"))}
  {_row("Année de construction", b.get("construction_year"))}
  {_row("Hauteur moyenne", b.get("height_m"), " m")}
  {_row("Logements", b.get("dwellings"))}
  {_row("Matériaux des murs", b.get("wall_material"))}
  {_row("Matériaux du toit", b.get("roof_material"))}
</table>
{_dia_html(data.get("market_dia"))}

<h2>Risques</h2>
<table>
  {_row("Retrait-gonflement des argiles", (b.get("risks") or {}).get("clay_shrink_swell"))}
  {_row("Risques recensés dans la zone", zone_risks)}
  {_row("Rapport Géorisques", risks.get("report_url"))}
</table>

{_groundwater_html(gw)}
{_water_network_html(data.get("water_network") or {})}

<h2>Solaire</h2>
<table>
  {_row("Favorable au solaire thermique", {True: "oui", False: "non"}.get(solar.get("thermal_favourable")))}
  {_row("Potentiel annuel estimé", solar.get("thermal_potential_kwh_y"), " kWh/an")}
  {_row("Productible photovoltaïque (PVGIS)", round(pv["yield_kwh_per_kwc_y"]) if pv.get("yield_kwh_per_kwc_y") else None, " kWh/an par kWc installé")}
  {_row("Irradiation (inclinaison optimale)", round(pv["irradiation_kwh_m2_y"]) if pv.get("irradiation_kwh_m2_y") else None, " kWh/m²/an")}
</table>
{f'<p class="meta">{pv["assumptions"]}</p>' if pv.get("assumptions") else ""}

{_prices_html(data.get("prices"))}
{_local_taxes_html(data.get("local_taxes") or {})}
{_schools_html(data.get("schools") or {})}
{_commune_html(data.get("commune") or {})}

<footer>
  Sources : BDNB (CSTB), Base Adresse Nationale, Géorisques — Licence Ouverte, attributions requises.
  Document informatif généré automatiquement à partir de données ouvertes : il ne remplace ni un
  diagnostic de performance énergétique (DPE) officiel, ni un état des risques et pollutions (ERP)
  réglementaire. Une question sur cette fiche : contact@confinia.io
</footer>
{_context_page(data, photos, map_img, aerial_img, aerial_parcels, aerial_outline)}
{_traceability_annex(data, photos)}
"""
    return html


def _target_overlay(outline: str | None) -> str:
    """Le tracé posé sur la photo.

    DEUX traits superposés : un large et sombre en dessous, un fin et clair
    au-dessus. Un trait d'une seule couleur disparaît — le clair sur une toiture
    en tuiles claires, le sombre sur des arbres. Le liseré garantit le contraste
    quel que soit ce qu'il y a dessous.
    """
    if outline:
        shape = (f'<polygon points="{outline}" fill="rgba(0,224,255,0.12)" '
                 'stroke="#00303a" stroke-width="1.4" stroke-linejoin="round"/>'
                 f'<polygon points="{outline}" fill="none" '
                 'stroke="#00E0FF" stroke-width="0.7" stroke-linejoin="round"/>')
    else:
        # Sans géométrie, la photo est de toute façon centrée sur le point :
        # un réticule au centre vaut mieux qu'aucune indication.
        shape = ('<circle cx="50" cy="50" r="7" fill="none" stroke="#00303a" '
                 'stroke-width="1.6"/>'
                 '<circle cx="50" cy="50" r="7" fill="none" stroke="#00E0FF" '
                 'stroke-width="0.8"/>')
    return (f'<svg viewBox="0 0 100 100" preserveAspectRatio="none">{shape}</svg>')


def _context_page(data: dict, photos: list | None, map_img: str | None = None,
                  aerial_img: str | None = None, aerial_parcels: str | None = None,
                  aerial_outline: str | None = None) -> str:
    """Second PDF page: third-party context — a rendered DPE-3D map of the
    building (#88) + Panoramax imagery. Falls back to an OSM link when the map
    render is unavailable."""
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
        # Auteur et licence sous CHAQUE image : l'attribution est une obligation
        # des licences libres, pas une politesse — et elle dit au lecteur d'où
        # vient ce qu'il regarde.
        credit = " · ".join(x for x in (p.get("source", "Panoramax"),
                                        p.get("author"), p.get("licence", "CC-BY-SA")) if x)
        title = p.get("title")
        caption = f"{title} — {credit}" if title else credit
        return f'<div class="pic">{inner}<div class="cap">{caption}</div></div>'

    pics = "".join(_pic(p) for p in photos[:4] if p.get("sd") or p.get("thumb"))
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
{(f'<h2>Vue aérienne</h2><div class="aerial"><img class="map3d" src="{aerial_img}"/>'
   + (f'<img class="parcels" src="{aerial_parcels}"/>' if aerial_parcels else '')
   + _target_overlay(aerial_outline) + '</div>'
   '<div class="cap">Photo aérienne IGN (BD ORTHO)'
   + (' et limites de parcelles (Parcellaire Express)' if aerial_parcels else '')
   + ' — Licence Ouverte. '
   + ('Le bâtiment concerné est entouré en cyan. ' if aerial_outline
      else 'Le bâtiment concerné est au centre du repère. ')
   + 'Le terrain, les arbres, les annexes et les accès, que nulle donnée '
   'structurée ne décrit.</div>') if aerial_img else ''}
{(f'<section class="bloc"><h2>Photos du lieu</h2>'
   f'<div class="pics">{pics}</div></section>') if pics else ''}
<h2>{"Localisation — carte 3D (DPE)" if map_img else "OpenStreetMap"}</h2>
{(f'<img class="map3d" src="{map_img}"/>'
  '<div class="cap">Bâtiment ciblé en pleine opacité (voisins atténués), coloré par classe DPE. '
  'Limites de parcelles en orange. '
  'Zoom 18, inclinaison 60°. Fond : OpenStreetMap et contributeurs (ODbL) · Bâtiments &amp; DPE : BDNB (CSTB) '
  '· Parcelles : IGN Parcellaire Express (Licence Ouverte).</div>')
 if map_img else
 f'<table><tr><td class="k" style="width:30%">Voir la zone sur OSM</td><td>{osm}</td></tr></table>'}
<footer>
  Imagerie : Panoramax (CC-BY-SA 4.0) et Wikimedia Commons, auteur et licence indiqués
  sous chaque photo. Cartographie : OpenStreetMap et contributeurs (ODbL).
  Informations de contexte, non contractuelles.
</footer>
<style>
  .map3d {{ width: 100%; border-radius: 4pt; margin-bottom: 3pt; }}
  /* Le contour est POSÉ sur la photo : sans lui, cinq pavillons d'un
     lotissement se ressemblent et le lecteur ne sait pas lequel est le sien. */
  .aerial {{ position: relative; line-height: 0; }}
  .aerial svg {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; }}
  /* Les limites de parcelles, posées sur la photo : « où s'arrête le terrain »
     est une des premières questions d'un acheteur. Sur le document, le numéro
     de parcelle a du sens — c'est la référence cadastrale, celle qu'un notaire
     emploie. À l'écran il ne servait à rien et masquait le reste. */
  .aerial .parcels {{ position: absolute; top: 0; left: 0; width: 100%;
                      height: 100%; border-radius: 4pt; opacity: 0.85; }}
  .map3d + .cap {{ font-size: 7.5pt; color: #888; margin-bottom: 4pt; }}
  .pics {{ display: flex; gap: 8pt; flex-wrap: wrap; }}
  /* Titre et photos SOLIDAIRES. `.pics` est un conteneur flex, que WeasyPrint
     traite comme insécable : il basculait donc en entier à la page suivante en
     laissant son titre derrière, suivi d'un grand blanc. `break-after: avoid`
     sur le titre n'y change rien — le moteur ne repousse pas la boîte qui
     précède. Les enfermer dans un même bloc les fait voyager ensemble.
     Si le bloc dépassait une page entière, la règle serait ignorée et l'on
     retomberait sur l'ancien comportement : quatre photos tiennent largement. */
  .bloc {{ break-inside: avoid; page-break-inside: avoid; }}
  .pic img.flat {{ width: 240pt; border-radius: 4pt; }}
  /* Central forward crop of an equirectangular 360 (2:1 image): box shows the
     central 1/4 width (90 deg) x 1/4 height (45 deg). */
  .pic .crop {{ width: 240pt; height: 120pt; overflow: hidden; border-radius: 4pt; }}
  .pic .crop img {{ width: 960pt; margin-left: -360pt; margin-top: -180pt; }}
  .pic .cap {{ font-size: 7pt; color: #888; }}
</style>"""
