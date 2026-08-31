"""Les tableaux de bord et l'instrumentation, comparés l'un à l'autre (#351).

« No data » sur un panneau peut vouloir dire deux choses : le compteur n'a
jamais été incrémenté (zéro, honnête), ou son nom est faux dans la requête
(panne muette, qui se lit comme un zéro plausible pendant des mois). Le
premier cas est normal ; le second doit casser la suite, pas attendre qu'un
opérateur s'interroge devant un écran.
"""
import json
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
TABLEAUX = sorted((RACINE / "monitoring/grafana/dashboards").glob("*.json"))
# Suffixes ajoutés par l'export OTel -> Prometheus.
SUFFIXES = ("_total", "_bucket", "_sum", "_count", "_seconds_bucket",
            "_seconds_sum", "_seconds_count", "_seconds")


def _metriques_du_code() -> set[str]:
    source = (RACINE / "api/app/main.py").read_text()
    # Toutes les formes d'instrumentation, jauges observables comprises : la
    # première version de ce test ne connaissait que les compteurs et accusait
    # à tort les métriques Keycloak.
    return set(re.findall(r'create_[a-z_]+\(\s*"(ecobuilding_[^"]+)"', source))


# Affichées à dessein alors que rien ne les émet encore : le bandeau du
# tableau FinOps le dit lui-même (« populate once Polar is wired … Nothing
# here is faked »). Toute AUTRE métrique absente est une faute de frappe.
ATTENDUES_PLUS_TARD = {
    "ecobuilding_pro_subscriptions",   # #292 : ouverture des paiements
    "ecobuilding_mrr_eur",             # idem
}


def _metriques_des_tableaux() -> dict[str, set[str]]:
    trouvees: dict[str, set[str]] = {}
    for f in TABLEAUX:
        noms = set(re.findall(r"\becobuilding_[a-z0-9_]+", f.read_text()))
        if noms:
            trouvees[f.name] = noms
    return trouvees


def test_les_tableaux_existent():
    assert TABLEAUX, "aucun tableau provisionné trouvé"


def test_chaque_metrique_affichee_existe_dans_le_code():
    connues = _metriques_du_code()
    inconnues = []
    for fichier, noms in _metriques_des_tableaux().items():
        for nom in noms:
            base = nom
            for s in sorted(SUFFIXES, key=len, reverse=True):
                if base.endswith(s):
                    base = base[: -len(s)]
                    break
            if base not in connues and base not in ATTENDUES_PLUS_TARD:
                inconnues.append(f"{fichier}: {nom}")
    assert not inconnues, (
        "métriques affichées mais jamais émises par l'API (faute de frappe ?) : "
        + ", ".join(sorted(inconnues))
        + f"\nconnues : {sorted(connues)}")
