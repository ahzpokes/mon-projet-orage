# ============================================================
# generer_meteo.py
# Version "SP2 d'abord, logs clairs, zéro devinette"
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

# ---------- CONFIG ----------
LAT_MIN, LAT_MAX = 42.0, 55.5
LON_MIN, LON_MAX = -5.0, 16.0
PAS_GRILLE = 0.25
ECHEANCES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 15, 18, 21, 24]

MF_API_AROME = "https://public-api.meteofrance.fr/previnum/DPPaquetAROME/v1"
MF_API_AROME_PI = "https://public-api.meteofrance.fr/previnum/DPPaquetAROMEPI/v1"
GRILLE_AROME = "0.025"

# SP2 : paquet CAPE_INS selon la doc Météo-France
AROME_CAPE_PKG_ID = "SP2"
AROME_PI_CAPE_PKG_ID = "SP2"

ICON_BASE = "https://opendata.dwd.de/weather/nwp/icon-d2/grib"
CYCLES_ICON = [21, 18, 15, 12, 9, 6, 3, 0]

# ---------- OUTILS ----------
def snap(coord):
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
    if t250 is not None and t200 is not None:
        if t200 <= t250:
            fl_tropo = pression_vers_fl(200)
        elif t300 is not None and t250 <= t300:
            fl_tropo = pression_vers_fl(250)
        else:
            fl_tropo = pression_vers_fl(300)
    else:
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

# ---------- Météo-France ----------
def dernier_reseau(api_base, token, paquet):
    print(f"   -> Recherche du dernier réseau pour le paquet {paquet}")
    try:
        url = f"{api_base}/models/AROME/grids/{GRILLE_AROME}/packages/{paquet}"
        r = requests.get(url, headers={"Authorization": f"Bearer {token}", "accept": "text/json"}, timeout=60)
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
        print("      Aucun referencetime trouvé dans links")
    except Exception as e:
        print(f"      !! Echec réseau paquet {paquet} : {e}")
    now = datetime.now(timezone.utc)
    run = now.replace(hour=(now.hour // 3) * 3, minute=0, second=0, microsecond=0)
    fallback = run.strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"      Repli réseau théorique : {fallback}")
    return fallback


def telecharger_paquet(api_base, token, paquet, referencetime, tranche, dossier):
    url = f"{api_base}/models/AROME/grids/{GRILLE_AROME}/packages/{paquet}/productARO"
    params = {"referencetime": referencetime, "time": tranche, "format": "grib2"}
    try:
        r = requests.get(url, params=params, headers={"Authorization": f"Bearer {token}", "accept": "*/*"}, timeout=600)
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


def telecharger_arome_modele(api_base, token, nom_modele, paquet_cape):
    print(f">> {nom_modele}...")
    if not token:
        print(f"   !! Token absent pour {nom_modele}")
        return {}

    print(f"   Paquet CAPE utilisé : {paquet_cape}")
    dossier = tempfile.mkdtemp()
    donnees = {}

    try:
        rt = dernier_reseau(api_base, token, paquet_cape)
        tranches = ["00H06H", "07H12H", "13H18H", "19H24H"]
        for tranche in tranches:
            chemin_cape = telecharger_paquet(api_base, token, paquet_cape, rt, tranche, dossier)
            if not chemin_cape:
                continue
            try:
                capes = extraire_grib(chemin_cape, filtre=None, mode="max")
                print(f"      CAPE extrait pour {tranche} : {sorted(capes.keys())}")
                for h, vals in capes.items():
                    donnees.setdefault(h, {})["cape"] = vals
            except Exception as e:
                print(f"      !! Décodage CAPE {tranche} : {e}")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    if not donnees:
        print(f"   !! Aucune donnée extraite pour {nom_modele}")
    return donnees

# ---------- ICON-D2 ----------
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
                cellules_cape = points_zone(ds["latitude"].values, ds["longitude"].values, donnees.values, mode="max")
                resultat[h] = {"cape": cellules_cape}
                ds.close()
                print(f"   H+{h} : {len(cellules_cape)} points")
            except Exception as e:
                print(f"   !! Décodage ICON-D2 H+{h} : {e}")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    return resultat

# ---------- FUSION ----------
def compiler_points():
    t_arome = os.environ.get("METEOFRANCE_TOKEN", "")
    t_pi = os.environ.get("METEOFRANCE_TOKEN_PI", "")

    d_pi = telecharger_arome_modele(MF_API_AROME_PI, t_pi, "AROME-PI", AROME_PI_CAPE_PKG_ID)
    d_aro = telecharger_arome_modele(MF_API_AROME, t_arome, "AROME", AROME_CAPE_PKG_ID)
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
                        "t300": None,
                        "t250": None,
                        "t200": None,
                        "modele": src_nom,
                    }

        points_finaux = []
        for v in cellules.values():
            if v["cape"] >= 500:
                points_finaux.append({
                    "lat": v["lat"],
                    "lon": v["lon"],
                    "cape": round(v["cape"]),
                    "top_cb": calculer_top_cb(v["cape"], v["t300"], v["t250"], v["t200"]),
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
    print(f">> Fichier sauvegardé : {chemin} ({os.path.getsize(chemin) // 1024} Ko)")


if __name__ == "__main__":
    main()
