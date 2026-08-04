# ============================================================
# generer_meteo.py
# Fusion de 3 modèles : AROME-PI, AROME classique, ICON-D2
# Pas horaire ciblé : H+1 à H+9, puis H+12, 15, 18, 21, 24
# ============================================================
import os
import json
import bz2
import math
import shutil
import tempfile
from datetime import datetime, timezone, timedelta

import requests
import numpy as np

# ---------- CONFIGURATION ----------
LAT_MIN, LAT_MAX = 42.0, 55.5       # France, Allemagne, Benelux, Suisse
LON_MIN, LON_MAX = -5.0, 16.0
PAS_GRILLE = 0.25                   # Résolution de la grille
ECHEANCES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 15, 18, 21, 24]
NB_HEURES = max(ECHEANCES)

# API Météo-France
MF_API = "https://public-api.meteofrance.fr/previnum/DPPaquetAROME/v1"
MF_API_PI = "https://public-api.meteofrance.fr/previnum/DPPaquetAROMEPI/v1"
GRILLE_AROME = "0.025"              

# DWD ICON-D2
ICON_BASE = "https://opendata.dwd.de/weather/nwp/icon-d2/grib"
CYCLES_ICON = [21, 18, 15, 12, 9, 6, 3, 0]

# ============================================================
# OUTILS COMMUNS
# ============================================================
def snap(coord):
    return round(round(coord / PAS_GRILLE) * PAS_GRILLE, 3)

def telecharger_grib_dwd(url, dossier):
    try:
        r = requests.get(url, timeout=120)
        if r.status_code != 200: return None
        brut = bz2.decompress(r.content)
        fd, chemin = tempfile.mkstemp(suffix=".grib2", dir=dossier)
        with os.fdopen(fd, "wb") as f: f.write(brut)
        return chemin
    except Exception: return None

def points_zone(lats, lons, valeurs, mode="max"):
    masque_lat = (lats >= LAT_MIN) & (lats <= LAT_MAX)
    masque_lon = (lons >= LON_MIN) & (lons <= LON_MAX)
    sous = valeurs[np.ix_(masque_lat, masque_lon)]
    lats_z, lons_z = lats[masque_lat], lons[masque_lon]
    cellules = {}
    ii, jj = np.where(~np.isnan(sous))
    for a, b in zip(ii, jj):
        cle = (snap(float(lats_z[a])), snap(float(lons_z[b])))
        v = float(sous[a, b])
        if cle not in cellules: cellules[cle] = v
        elif mode == "max" and v > cellules[cle]: cellules[cle] = v
        elif mode == "min" and v < cellules[cle]: cellules[cle] = v
    return cellules

def pression_vers_fl(p_hpa):
    return round(145366 * (1 - (p_hpa / 1013.25) ** 0.190284) / 100)

def calculer_top_cb(cape, t300=None, t250=None, t200=None):
    if cape is None or cape < 500: return 0
    fl_cape = 250 + (cape / 3000.0) * 150
    if t250 is not None and t200 is not None:
        if t200 <= t250: fl_tropo = pression_vers_fl(200)
        elif t300 is not None and t250 <= t300: fl_tropo = pression_vers_fl(250)
        else: fl_tropo = pression_vers_fl(300)
    else: fl_tropo = 360
    return int(min(fl_cape, fl_tropo + 20))

# ============================================================
# DÉCODAGE GRIB
# ============================================================
def extraire_grib(chemin, filtre=None, niveau=None, mode="max"):
    import xarray as xr
    options = {"engine": "cfgrib"}
    if filtre: options["backend_kwargs"] = {"filter_by_keys": filtre}
    sortie = {}
    try:
        ds = xr.open_dataset(chemin, **options)
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
                    sortie[h] = points_zone(ds.latitude.values, ds.longitude.values, sous.values, mode=mode)
        else:
            sortie[1] = points_zone(ds.latitude.values, ds.longitude.values, donnees.values, mode=mode)
    except Exception as e:
        print(f"Erreur cfgrib: {e}")
    return sortie

# ============================================================
# ICON-D2
# ============================================================
def telecharger_icon():
    print(">> ICON-D2...")
    now = datetime.now(timezone.utc)
    date_str, cycle = None, None
    for j in range(2):
        d = now - timedelta(days=j)
        ds = d.strftime("%Y%m%d")
        for c in CYCLES_ICON:
            if j == 0 and c > now.hour: continue
            url = f"{ICON_BASE}/{c:02d}/cape_ml/icon-d2_germany_regular-lat-lon_single-level_{ds}{c:02d}_001_CAPE_ML.grib2.bz2"
            try:
                if requests.head(url, timeout=10).status_code == 200:
                    date_str, cycle = ds, c
                    break
            except: pass
        if cycle is not None: break
    
    if not cycle: return {}
    print(f"   Réseau : {date_str} {cycle:02d}h")
    
    dossier = tempfile.mkdtemp()
    resultat = {}
    try:
        for h in ECHEANCES:
            url = f"{ICON_BASE}/{cycle:02d}/cape_ml/icon-d2_germany_regular-lat-lon_single-level_{date_str}{cycle:02d}_{h:03d}_CAPE_ML.grib2.bz2"
            chemin = telecharger_grib_dwd(url, dossier)
            if chemin:
                # ICON-D2 grib 1 fichier = 1 echeance, step n'est pas tjs une dimension propre, forçons le step=h
                import xarray as xr
                try:
                    ds = xr.open_dataset(chemin, engine="cfgrib")
                    val = list(ds.data_vars)[0]
                    resultat[h] = {"cape": points_zone(ds.latitude.values, ds.longitude.values, ds[val].values, mode="max")}
                except: pass
    finally:
        shutil.rmtree(dossier, ignore_errors=True)
    return resultat

# ============================================================
# MÉTÉO-FRANCE (AROME / AROME-PI)
# ============================================================
def telecharger_mf(api_base, token, nom_modele, suffixe_paquet=""):
    print(f">> {nom_modele}...")
    if not token: return {}
    
    # 1. Chercher les paquets CAPE et Isobare
    # En RESTful, on interroge /packages
    def trouver_paquet(mot_cle):
        try:
            r = requests.get(f"{api_base}/models/AROME/grids/{GRILLE_AROME}/packages", headers={"Authorization": f"Bearer {token}", "accept": "text/json"})
            links = r.json().get("links", [])
            for l in links:
                href = l.get("href","")
                if "packages/" in href:
                    p = href.split("packages/")[1].split("?")[0]
                    desc = requests.get(f"{api_base}/models/AROME/grids/{GRILLE_AROME}/packages/{p}", headers={"Authorization": f"Bearer {token}", "accept": "text/json"}).json()
                    if mot_cle.lower() in desc.get("description","").lower():
                        return p
        except: pass
        return None

    p_cape = trouver_paquet("CAPE")
    p_t = trouver_paquet("isobare")
    if not p_cape:
        print(f"   !! Paquet CAPE {nom_modele} introuvable")
        return {}
    
    # 2. Chercher le réseau le plus récent
    def dernier_reseau(paquet):
        try:
            desc = requests.get(f"{api_base}/models/AROME/grids/{GRILLE_AROME}/packages/{paquet}", headers={"Authorization": f"Bearer {token}", "accept": "text/json"}).json()
            rts = [l.get("href").split("referencetime=")[1].split("&")[0] for l in desc.get("links",[]) if "referencetime=" in l.get("href","")]
            return max(rts) if rts else None
        except: return None
    
    rt = dernier_reseau(p_cape)
    if not rt: return {}
    print(f"   Réseau : {rt}")

    # 3. Télécharger
    tranches = ["00H06H", "07H12H", "13H18H", "19H24H"] if nom_modele == "AROME" else ["00H06H"]
    dossier = tempfile.mkdtemp()
    donnees = {}
    try:
        for tranche in tranches:
            # CAPE
            r = requests.get(f"{api_base}/models/AROME/grids/{GRILLE_AROME}/packages/{p_cape}/productARO",
                             params={"referencetime": rt, "time": tranche, "format": "grib2"},
                             headers={"Authorization": f"Bearer {token}", "accept": "*/*"})
            if r.status_code == 200:
                fd, c_cape = tempfile.mkstemp(suffix=".grib2", dir=dossier)
                with os.fdopen(fd, "wb") as f: f.write(r.content)
                capes = extraire_grib(c_cape, filtre={"shortName": "cape"}, mode="max")
                for h, vals in capes.items():
                    donnees.setdefault(h, {})["cape"] = vals

            # Températures
            if p_t:
                r_t = requests.get(f"{api_base}/models/AROME/grids/{GRILLE_AROME}/packages/{p_t}/productARO",
                                   params={"referencetime": rt, "time": tranche, "format": "grib2"},
                                   headers={"Authorization": f"Bearer {token}", "accept": "*/*"})
                if r_t.status_code == 200:
                    fd, c_t = tempfile.mkstemp(suffix=".grib2", dir=dossier)
                    with os.fdopen(fd, "wb") as f: f.write(r_t.content)
                    for niv in [300, 250, 200]:
                        ts = extraire_grib(c_t, filtre={"shortName": "t"}, niveau=niv, mode="min")
                        for h, vals in ts.items():
                            donnees.setdefault(h, {}).setdefault("t", {})[niv] = vals
    finally:
        shutil.rmtree(dossier, ignore_errors=True)
    return donnees

# ============================================================
# FUSION PESSIMISTE
# ============================================================
def compiler_points():
    t_arome = os.environ.get("METEOFRANCE_TOKEN", "")
    t_pi = os.environ.get("METEOFRANCE_TOKEN_PI", "")
    
    d_pi = telecharger_mf(MF_API_PI, t_pi, "AROME-PI")
    d_aro = telecharger_mf(MF_API, t_arome, "AROME")
    d_icon = telecharger_icon()
    
    print(">> Fusion pessimiste...")
    fusion = []
    
    for h in ECHEANCES:
        cellules = {}
        for source, src_nom in [(d_pi, "AROME-PI"), (d_aro, "AROME"), (d_icon, "ICON-D2")]:
            if h not in source: continue
            capes = source[h].get("cape", {})
            ts = source[h].get("t", {})
            for cle, cape_val in capes.items():
                if cle not in cellules or cape_val > cellules[cle]["cape"]:
                    cellules[cle] = {
                        "lat": cle[0], "lon": cle[1], "cape": cape_val,
                        "t300": ts.get(300, {}).get(cle),
                        "t250": ts.get(250, {}).get(cle),
                        "t200": ts.get(200, {}).get(cle),
                        "modele": src_nom
                    }
        
        points_finaux = []
        for v in cellules.values():
            if v["cape"] > 100:
                points_finaux.append({
                    "lat": v["lat"], "lon": v["lon"], "cape": round(v["cape"]),
                    "top_cb": calculer_top_cb(v["cape"], v["t300"], v["t250"], v["t200"]),
                    "modele": v["modele"]
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
        "previsions": fusion,
    }
    os.makedirs("public", exist_ok=True)
    chemin = os.path.join("public", "previsions_orages.json")
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False)

if __name__ == "__main__":
    main()
