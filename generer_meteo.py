# ============================================================
# generer_meteo.py
# Version "SP2 d'abord, mais auto-détection CAPE_INS"
#
# Modèles :
#   - AROME-PI (Météo-France)
#   - AROME classique (Météo-France)
#   - ICON-D2 (DWD)
#
# Sortie : public/previsions_orages.json
# ============================================================
import os
import json
import bz2
import shutil
import tempfile
from datetime import datetime, timezone, timedelta

import requests
import numpy as np

# ---------- CONFIG GÉO ----------
LAT_MIN, LAT_MAX = 42.0, 55.5   # France, Allemagne, Suisse, Benelux
LON_MIN, LON_MAX = -5.0, 16.0
PAS_GRILLE = 0.25

# Pas de temps demandés (H+1..9 puis 12,15,18,21,24)
ECHEANCES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 15, 18, 21, 24]

# ---------- API Météo-France ----------
# API "Paquets AROME" (classique)
MF_API_AROME = "https://public-api.meteofrance.fr/previnum/DPPaquetAROME/v1"
# API "Paquets AROME-PI" (prévision immédiate)
MF_API_AROME_PI = "https://public-api.meteofrance.fr/previnum/DPPaquetAROMEPI/v1"

# Grilles (à adapter si besoin selon ton portail, mais 0.025 est la doc standard Europe) [71]
GRILLE_AROME = "0.025"
GRILLE_AROME_PI = "0.025"  # si ton portail indique un autre ID de grille pour PI, tu le mets ici

# ---------- ICON-D2 ----------
ICON_BASE = "https://opendata.dwd.de/weather/nwp/icon-d2/grib"
CYCLES_ICON = [21, 18, 15, 12, 9, 6, 3, 0]

# ============================================================
# OUTILS GÉNÉRIQUES
# ============================================================
def snap(coord: float) -> float:
    """Arrondit une coordonnée sur la grille commune (0.25°)."""
    return round(round(coord / PAS_GRILLE) * PAS_GRILLE, 3)


def points_zone(lats, lons, valeurs, mode="max"):
    """
    Découpe la zone utile puis agrège chaque point du modèle sur la
    grille 0.25° commune. mode="max" garde la valeur la plus forte
    (CAPE pessimiste), mode="min" la plus froide (température).
    """
    masque_lat = (lats >= LAT_MIN) & (lats <= LAT_MAX)
    masque_lon = (lons >= LON_MIN) & (lons <= LON_MAX)
    sous = valeurs[np.ix_(masque_lat, masque_lon)]
    lats_z = lats[masque_lat]
    lons_z = lons[masque_lon]
    cellules = {}
    ii, jj = np.where(~np.isnan(sous))
    for a, b in zip(ii, jj):
        cle = (snap(float(lats_z[a])), snap(float(lons_z[b])))
        v = float(sous[a, b])
        if cle not in cellules:
            cellules[cle] = v
        elif mode == "max" and v > cellules[cle]:
            cellules[cle] = v
        elif mode == "min" and v < cellules[cle]:
            cellules[cle] = v
    return cellules


def pression_vers_fl(p_hpa: float) -> int:
    """Convertit une pression (hPa) en niveau de vol (FL)."""
    return round(145366 * (1 - (p_hpa / 1013.25) ** 0.190284) / 100)


def calculer_top_cb(cape, t300=None, t250=None, t200=None) -> int:
    """
    Estime le sommet des CB :
    - CAPE donne une hauteur théorique.
    - Les températures à 300/250/200 hPa donneraient une tropopause locale
      (ici simplifiée, car nous ne lisons pas encore les T isobares dans ce script).
    """
    if cape is None or cape < 500:
        return 0
    fl_cape = 250 + (cape / 3000.0) * 150  # 500 J/kg -> FL250, 3000 -> FL400
    fl_tropo = 360  # valeur standard si T indisponibles
    return int(min(fl_cape, fl_tropo + 20))


def extraire_grib(chemin, filtre=None, niveau=None, mode="max"):
    """
    Lit un GRIB2 via cfgrib/xarray et renvoie {échéance_h: {cellule: valeur}}.
    Si filtre=None, on prend la première variable présente (utile pour CAPE_INS).
    """
    import xarray as xr

    options = {"engine": "cfgrib"}
    if filtre is not None:
        options["backend_kwargs"] = {"filter_by_keys": filtre}

    sortie = {}
    ds = xr.open_dataset(chemin, **options)
    try:
        variable = list(ds.data_vars)[0]
        donnees = ds[variable]

        if niveau is not None:
            for nom_dim in ("isobaricInhPa", "level"):
                if nom_dim in donnees.dims:
                    donnees = donnees.sel({nom_dim: niveau}, method="nearest")
                    break

        if "step" in donnees.dims:
            steps_h = ds["step"].values / np.timedelta64(1, "h")
            for idx, sh in enumerate(steps_h):
                h = int(round(float(sh)))
                if h in ECHEANCES:
                    sous = donnees.isel(step=idx)
                    cellules = points_zone(
                        ds["latitude"].values,
                        ds["longitude"].values,
                        sous.values,
                        mode=mode,
                    )
                    sortie[h] = cellules
        else:
            sortie[1] = points_zone(
                ds["latitude"].values,
                ds["longitude"].values,
                donnees.values,
                mode=mode,
            )
    finally:
        ds.close()
    return sortie

# ============================================================
# Météo-France : LISTER LES PAQUETS ET TROUVER CAPE_INS
# ============================================================
def lister_paquets(api_base, token, grille):
    """
    Liste les paquets disponibles pour un modèle/grille donné.
    Affiche les IDs dans les logs pour diagnostic.
    """
    url = f"{api_base}/models/AROME/grids/{grille}/packages"
    print(f"   -> Listing des paquets via {url}")
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "accept": "text/json"},
            timeout=60,
        )
        print(f"      HTTP {r.status_code}")
        r.raise_for_status()
        data = r.json()
        ids = []
        for lien in data.get("links", []):
            href = lien.get("href", "")
            if "/packages/" in href:
                pkg_id = href.split("/packages/")[1].split("?")[0]
                ids.append(pkg_id)
        print(f"      Paquets disponibles : {ids}")
        return ids
    except Exception as e:
        print(f"      !! Echec listing paquets : {e}")
        return []


def paquet_avec_cape_ins(api_base, token, grille):
    """
    Essaie de trouver un paquet dont la description mentionne CAPE_INS.
    Si rien n'est trouvé, retourne None.
    """
    ids = lister_paquets(api_base, token, grille)
    if not ids:
        return None

    print("   -> Recherche d'un paquet contenant CAPE_INS dans sa description")
    for pkg in ids:
        url = f"{api_base}/models/AROME/grids/{grille}/packages/{pkg}"
        try:
            r = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}", "accept": "text/json"},
                timeout=60,
            )
            print(f"      Descripteur {pkg} -> HTTP {r.status_code}")
            if r.status_code != 200:
                continue
            desc = r.json()
            texte = json.dumps(desc).upper()
            if "CAPE_INS" in texte:
                print(f"      Paquet CAPE_INS trouvé : {pkg}")
                return pkg
        except Exception as e:
            print(f"      !! Echec lecture paquet {pkg} : {e}")
    print("      Aucun paquet avec CAPE_INS trouvé")
    return None


def dernier_reseau(api_base, token, grille, paquet):
    """
    Récupère le réseau le plus récent pour le paquet donné,
    via la description du paquet (liens avec referencetime).
    """
    print(f"   -> Recherche du dernier réseau pour le paquet {paquet}")
    try:
        url = f"{api_base}/models/AROME/grids/{grille}/packages/{paquet}"
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}", "accept": "text/json"},
            timeout=60,
        )
        print(f"      HTTP {r.status_code} sur {url}")
        r.raise_for_status()
        desc = r.json()
        rts = []
        for lien in desc.get("links", []):
            href = lien.get("href", "")
            if "referencetime=" in href:
                rt = href.split("referencetime=")[1].split("&")[0]
                rts.append(rt)
        if rts:
            rt = max(rts)
            print(f"      Réseau trouvé : {rt}")
            return rt
        print("      Aucun referencetime dans links")
    except Exception as e:
        print(f"      !! Echec réseau paquet {paquet} : {e}")
    now = datetime.now(timezone.utc)
    run = now.replace(hour=(now.hour // 3) * 3, minute=0, second=0, microsecond=0)
    fallback = run.strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"      Repli réseau théorique : {fallback}")
    return fallback


def telecharger_paquet(api_base, token, grille, paquet, referencetime, tranche, dossier):
    url = f"{api_base}/models/AROME/grids/{grille}/packages/{paquet}/productARO"
    params = {"referencetime": referencetime, "time": tranche, "format": "grib2"}
    try:
        r = requests.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {token}", "accept": "*/*"},
            timeout=600,
        )
        print(f"      Download {paquet} {tranche} -> HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"      !! Réponse non valide pour {paquet} {tranche}")
            return None
        fd, chemin = tempfile.mkstemp(suffix=".grib2", dir=dossier)
        with os.fdopen(fd, "wb") as f:
            f.write(r.content)
        return chemin
    except Exception as e:
        print(f"      !! Erreur téléchargement {paquet} {tranche} : {e}")
        return None


def telecharger_arome_modele(api_base, grille, token, nom_modele):
    """
    Télécharge CAPE_INS pour AROME ou AROME-PI.
    Retour : dict {heure: {"cape": {cellule: valeur}}}
    """
    print(f">> {nom_modele}...")
    if not token:
        print(f"   !! Token absent pour {nom_modele}")
        return {}

    # 1) Trouver le paquet CAPE_INS
    paquet_cape = paquet_avec_cape_ins(api_base, token, grille)
    if not paquet_cape:
        print(f"   !! Aucun paquet CAPE_INS trouvé pour {nom_modele}")
        return {}

    dossier = tempfile.mkdtemp()
    donnees = {}

    try:
        # 2) réseau le plus récent
        rt = dernier_reseau(api_base, token, grille, paquet_cape)

        # 3) tranches temporelles (doc standard AROME : 00H06H, 07H12H, 13H18H, 19H24H)
        tranches = ["00H06H", "07H12H", "13H18H", "19H24H"]
        for tranche in tranches:
            chemin_cape = telecharger_paquet(
                api_base, token, grille, paquet_cape, rt, tranche, dossier
            )
            if not chemin_cape:
                continue
            try:
                capes = extraire_grib(chemin_cape, filtre=None, mode="max")
                print(f"      CAPE_INS extrait pour {tranche} : {sorted(capes.keys())}")
                for h, vals in capes.items():
                    donnees.setdefault(h, {})["cape"] = vals
            except Exception as e:
                print(f"      !! Décodage CAPE_INS {tranche} : {e}")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    if not donnees:
        print(f"   !! Aucune CAPE_INS extraite pour {nom_modele}")
    return donnees

# ============================================================
# ICON-D2 (DWD)
# ============================================================
def telecharger_grib_dwd(url, dossier):
    try:
        r = requests.get(url, timeout=180)
        if r.status_code != 200:
            return None
        brut = bz2.decompress(r.content)
        fd, chemin = tempfile.mkstemp(suffix=".grib2", dir=dossier)
        with os.fdopen(fd, "wb") as f:
            f.write(brut)
        return chemin
    except Exception:
        return None


def dernier_run_icon():
    maintenant = datetime.now(timezone.utc)
    for recul_jours in range(2):
        jour = maintenant - timedelta(days=recul_jours)
        date = jour.strftime("%Y%m%d")
        for cycle in CYCLES_ICON:
            if recul_jours == 0 and cycle > maintenant.hour:
                continue
            url = f"{ICON_BASE}/{cycle:02d}/cape_ml/icon-d2_germany_regular-lat-lon_single-level_{date}{cycle:02d}_001_CAPE_ML.grib2.bz2"
            try:
                r = requests.head(url, timeout=15)
                if r.status_code == 200:
                    return date, cycle
            except requests.RequestException:
                pass
    return None, None


def telecharger_icon():
    print(">> ICON-D2...")
    date, cycle = dernier_run_icon()
    if not date:
        print("   !! Aucun réseau ICON-D2 trouvé")
        return {}

    print(f"   Réseau : {date} {cycle:02d}h UTC")
    dossier = tempfile.mkdtemp()
    resultat = {}

    import xarray as xr

    try:
        for h in ECHEANCES:
            url = f"{ICON_BASE}/{cycle:02d}/cape_ml/icon-d2_germany_regular-lat-lon_single-level_{date}{cycle:02d}_{h:03d}_CAPE_ML.grib2.bz2"
            chemin = telecharger_grib_dwd(url, dossier)
            if not chemin:
                print(f"   .. échéance {h}h absente")
                continue
            try:
                ds = xr.open_dataset(chemin, engine="cfgrib")
                variable = list(ds.data_vars)[0]
                donnees = ds[variable]
                cellules_cape = points_zone(
                    ds["latitude"].values,
                    ds["longitude"].values,
                    donnees.values,
                    mode="max",
                )
                resultat[h] = {"cape": cellules_cape}
                ds.close()
                print(f"   H+{h} : {len(cellules_cape)} points")
            except Exception as e:
                print(f"   !! Décodage ICON-D2 H+{h} : {e}")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    return resultat

# ============================================================
# FUSION PESSIMISTE
# ============================================================
def compiler_points():
    t_arome = os.environ.get("METEOFRANCE_TOKEN", "")
    t_pi = os.environ.get("METEOFRANCE_TOKEN_PI", "")

    d_pi = telecharger_arome_modele(MF_API_AROME_PI, GRILLE_AROME_PI, t_pi, "AROME-PI")
    d_aro = telecharger_arome_modele(MF_API_AROME, GRILLE_AROME, t_arome, "AROME")
    d_icon = telecharger_icon()

    print(">> Fusion pessimiste globale...")
    fusion = []

    for h in ECHEANCES:
        cellules = {}
        for source, src_nom in (
            (d_pi, "AROME-PI"),
            (d_aro, "AROME"),
            (d_icon, "ICON-D2"),
        ):
            if h not in source:
                continue
            capes = source[h].get("cape", {})
            for cle, cape_val in capes.items():
                if cle not in cellules or cape_val > cellules[cle]["cape"]:
                    cellules[cle] = {
                        "lat": cle[0],
                        "lon": cle[1],
                        "cape": cape_val,
                        "t300": None,
                        "t250": None,
                        "t200": None,
                        "modele": src_nom,
                    }

        points_finaux = []
        for v in cellules.values():
            if v["cape"] >= 500:
                points_finaux.append(
                    {
                        "lat": v["lat"],
                        "lon": v["lon"],
                        "cape": round(v["cape"]),
                        "top_cb": calculer_top_cb(
                            v["cape"], v["t300"], v["t250"], v["t200"]
                        ),
                        "modele": v["modele"],
                    }
                )
        fusion.append({"heure": h, "points": points_finaux})
        print(f"   H+{h} : {len(points_finaux)} cellules orageuses")

    return fusion


def main():
    fusion = compiler_points()
    maintenant = datetime.now(timezone.utc)
    sortie = {
        "genere_le": maintenant.isoformat(),
        "heure_reference": maintenant.strftime("%Y-%m-%d %H:%M UTC"),
        "pas_horaires": ECHEANCES,
        "sources": [
            "AROME-PI (Météo-France)",
            "AROME (Météo-France)",
            "ICON-D2 (DWD)",
        ],
        "previsions": fusion,
    }

    os.makedirs("public", exist_ok=True)
    chemin = os.path.join("public", "previsions_orages.json")
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False)
    print(f">> Fichier sauvegardé : {chemin} ({os.path.getsize(chemin) // 1024} Ko)")


if __name__ == "__main__":
    main()