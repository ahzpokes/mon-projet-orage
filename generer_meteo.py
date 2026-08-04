# ============================================================
# generer_meteo.py
# AROME-PI via WCS + AROME classique en repli + ICON-D2
# Fusion pessimiste CAPE maximale
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

LAT_MIN, LAT_MAX = 42.0, 55.5
LON_MIN, LON_MAX = -5.0, 16.0
PAS_GRILLE = 0.25
ECHEANCES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 15, 18, 21, 24]

# ---------- Météo-France ----------
# AROME-PI : WCS officiel
AROMEPI_WCS = "https://public-api.meteofrance.fr/public/aromepi/1.0/wcs/MF-NWP-HIGHRES-AROMEPI-001-FRANCE-WCS"
# AROME classique : tentative API/paquets (si ton token est autorisé)
AROME_API = "https://public-api.meteofrance.fr/previnum/DPPaquetAROME/v1"

# ---------- DWD ICON-D2 ----------
ICON_BASE = "https://opendata.dwd.de/weather/nwp/icon-d2/grib"
ICON_CYCLES = [21, 18, 15, 12, 9, 6, 3, 0]


def snap(coord: float) -> float:
    return round(round(coord / PAS_GRILLE) * PAS_GRILLE, 3)


def points_zone(lats, lons, valeurs, mode="max"):
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


def pression_vers_fl(p_hpa):
    return round(145366 * (1 - (p_hpa / 1013.25) ** 0.190284) / 100)


def calculer_top_cb(cape, t300=None, t250=None, t200=None):
    if cape is None or cape < 500:
        return 0
    fl_cape = 250 + (cape / 3000.0) * 150
    fl_tropo = 360
    return int(min(fl_cape, fl_tropo + 20))


def extraire_grib(chemin, filtre=None, niveau=None, mode="max"):
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
                    sortie[h] = points_zone(ds["latitude"].values, ds["longitude"].values, sous.values, mode=mode)
        else:
            sortie[1] = points_zone(ds["latitude"].values, ds["longitude"].values, donnees.values, mode=mode)
    finally:
        ds.close()
    return sortie


# ============================================================
# AROME-PI via WCS
# ============================================================
def arome_pi_get_capabilities(token):
    url = f"{AROMEPI_WCS}/GetCapabilities"
    params = {"service": "WCS", "version": "2.0.1", "language": "fre"}
    r = requests.get(url, params=params, headers={"apikey": token}, timeout=60)
    print(f"   GetCapabilities AROME-PI -> HTTP {r.status_code}")
    r.raise_for_status()
    return r.text


def arome_pi_trouver_coverage_cape(token):
    """
    Cherche un coverage contenant 'CAPE' dans GetCapabilities.
    """
    xml = arome_pi_get_capabilities(token)
    # Très simple : on cherche les identifiants qui contiennent CAPE
    ids = []
    for chunk in xml.split("<wcs:CoverageId>")[1:]:
        cid = chunk.split("</wcs:CoverageId>")[0].strip()
        if "CAPE" in cid.upper():
            ids.append(cid)
    print(f"   Coverages CAPE détectés AROME-PI : {ids}")
    return ids[0] if ids else None


def arome_pi_extraire_cape(token):
    """
    Télécharge le coverage CAPE AROME-PI et le lit avec cfgrib.
    On laisse les paramètres temporels/zone au service WCS.
    """
    print(">> AROME-PI...")
    if not token:
        print("   !! Token AROME-PI manquant")
        return {}

    coverage = arome_pi_trouver_coverage_cape(token)
    if not coverage:
        print("   !! Aucun coverage CAPE trouvé dans AROME-PI")
        return {}

    dossier = tempfile.mkdtemp()
    donnees = {}

    try:
        # On demande un petit extrait géographique sur toute l'Europe utile
        # et on récupère le fichier brut pour décodage.
        # Les paramètres exacts peuvent varier selon le coverage ; si besoin,
        # le log GetCoverage dira l'erreur et on ajustera.
        url = f"{AROMEPI_WCS}/GetCoverage"
        params = {
            "service": "WCS",
            "version": "2.0.1",
            "coverageId": coverage,
            "format": "application/x-grib2",
        }

        r = requests.get(url, params=params, headers={"apikey": token}, timeout=600)
        print(f"   GetCoverage AROME-PI -> HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"   !! Echec GetCoverage AROME-PI : {r.text[:500]}")
            return {}

        fd, chemin = tempfile.mkstemp(suffix=".grib2", dir=dossier)
        with os.fdopen(fd, "wb") as f:
            f.write(r.content)

        # Lecture du GRIB
        capes = extraire_grib(chemin, filtre=None, mode="max")
        print(f"   CAPE AROME-PI extrait : {list(capes.keys())}")
        for h, vals in capes.items():
            donnees.setdefault(h, {})["cape"] = vals

    except Exception as e:
        print(f"   !! AROME-PI erreur : {e}")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    return donnees


# ============================================================
# AROME classique via API paquets (repli)
# ============================================================
def arome_classique_extraire(token):
    print(">> AROME...")
    if not token:
        print("   !! Token AROME manquant")
        return {}

    # On tente au moins le listing. Si ça renvoie 401, on s'arrête.
    try:
        url = f"{AROME_API}/models/AROME/grids/0.025/packages"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}", "accept": "text/json"}, timeout=60)
        print(f"   Listing paquets AROME -> HTTP {r.status_code}")
        if r.status_code != 200:
            print(f"   !! AROME non accessible : {r.text[:500]}")
            return {}
    except Exception as e:
        print(f"   !! AROME erreur : {e}")
        return {}

    # Si un jour ton token est autorisé, on pourra compléter ici.
    # Pour l’instant on retourne vide pour ne pas bloquer le script.
    print("   !! AROME classique prêt, mais extraction non activée dans cette version")
    return {}


# ============================================================
# ICON-D2
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
        for cycle in ICON_CYCLES:
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
                cellules_cape = points_zone(ds["latitude"].values, ds["longitude"].values, donnees.values, mode="max")
                resultat[h] = {"cape": cellules_cape}
                ds.close()
                print(f"   H+{h} : {len(cellules_cape)} points")
            except Exception as e:
                print(f"   !! Décodage ICON-D2 H+{h} : {e}")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    return resultat


# ============================================================
# FUSION
# ============================================================
def compiler_points():
    token_pi = os.environ.get("METEOFRANCE_TOKEN_PI", "")
    token_arome = os.environ.get("METEOFRANCE_TOKEN", "")

    d_pi = arome_pi_extraire_cape(token_pi)
    d_aro = arome_classique_extraire(token_arome)
    d_icon = telecharger_icon()

    print(">> Fusion pessimiste globale...")
    fusion = []

    for h in ECHEANCES:
        cellules = {}
        for source, src_nom in ((d_pi, "AROME-PI"), (d_aro, "AROME"), (d_icon, "ICON-D2")):
            if h not in source:
                continue
            capes = source[h].get("cape", {})
            for cle, cape_val in capes.items():
                if cle not in cellules or cape_val > cellules[cle]["cape"]:
                    cellules[cle] = {
                        "lat": cle[0],
                        "lon": cle[1],
                        "cape": cape_val,
                        "modele": src_nom,
                    }

        points_finaux = []
        for v in cellules.values():
            if v["cape"] >= 500:
                points_finaux.append({
                    "lat": v["lat"],
                    "lon": v["lon"],
                    "cape": round(v["cape"]),
                    "top_cb": calculer_top_cb(v["cape"]),
                    "modele": v["modele"],
                })

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
        "sources": ["AROME-PI (Météo-France)", "AROME (Météo-France)", "ICON-D2 (DWD)"],
        "previsions": fusion,
    }

    os.makedirs("public", exist_ok=True)
    chemin = os.path.join("public", "previsions_orages.json")
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False)
    print(f">> Fichier sauvegardé : {chemin}")


if __name__ == "__main__":
    main()