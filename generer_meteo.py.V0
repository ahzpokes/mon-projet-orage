# ============================================================
# generer_meteo.py
# Fusion de GFS (0.25°) et ICON-D2 (DWD)
# Solution de secours robuste pour pallier les erreurs API Météo-France
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

# ---------- ZONE ----------
LAT_MIN, LAT_MAX = 42.0, 55.5   # France, Allemagne, Suisse, Benelux
LON_MIN, LON_MAX = -5.0, 16.0
PAS_GRILLE = 0.25

# Échéances : H+1..9 puis H+12,15,18,21,24
ECHEANCES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 15, 18, 21, 24]

# ---------- ICON-D2 ----------
ICON_BASE = "https://opendata.dwd.de/weather/nwp/icon-d2/grib"
ICON_CYCLES = [21, 18, 15, 12, 9, 6, 3, 0]

# ---------- GFS (NCEP) ----------
# On utilise le serveur NOMADS de la NOAA (100% gratuit, pas de token)
GFS_BASE_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"

# ============================================================
# OUTILS COMMUNS
# ============================================================
def snap(coord: float) -> float:
    return round(round(coord / PAS_GRILLE) * PAS_GRILLE, 3)

def points_zone(lats, lons, valeurs, mode="max"):
    masque_lat = (lats >= LAT_MIN) & (lats <= LAT_MAX)
    masque_lon = (lons >= LON_MIN) & (lons <= LON_MAX)
    
    # Pour GFS, les longitudes sont parfois [0, 360]. On ajuste :
    lons_adj = np.where(lons > 180, lons - 360, lons)
    masque_lon_adj = (lons_adj >= LON_MIN) & (lons_adj <= LON_MAX)
    
    sous = valeurs[np.ix_(masque_lat, masque_lon_adj)]
    lats_z = lats[masque_lat]
    lons_z = lons_adj[masque_lon_adj]
    
    cellules = {}
    ii, jj = np.where(~np.isnan(sous))
    for a, b in zip(ii, jj):
        cle = (snap(float(lats_z[a])), snap(float(lons_z[b])))
        v = float(sous[a, b])
        if cle not in cellules:
            cellules[cle] = v
        elif mode == "max" and v > cellules[cle]:
            cellules[cle] = v
    return cellules

def calculer_top_cb(cape: float) -> int:
    """Top CB basé sur CAPE seule (simplifié)"""
    if cape is None or cape < 500:
        return 0
    fl_cape = 250 + (cape / 3000.0) * 150
    return int(min(fl_cape, 380))

# ============================================================
# GFS (NOAA/NCEP)
# ============================================================
def dernier_run_gfs():
    """Trouve le dernier run GFS (00, 06, 12, 18)"""
    now = datetime.now(timezone.utc)
    for hours_back in range(0, 48, 6):
        run_time = now - timedelta(hours=hours_back)
        cycle = (run_time.hour // 6) * 6
        date_str = run_time.strftime("%Y%m%d")
        
        # Test rapide sur H+0 pour voir si le run est dispo
        test_url = f"{GFS_BASE_URL}?file=gfs.t{cycle:02d}z.pgrb2.0p25.f000&var_CAPE=on&lev_surface=on&dir=%2Fgfs.{date_str}%2F{cycle:02d}%2Fatmos"
        try:
            r = requests.head(test_url, timeout=10)
            if r.status_code == 200:
                return date_str, cycle
        except:
            continue
    return None, None

def telecharger_gfs():
    print(">> GFS (NOAA)...")
    date_str, cycle = dernier_run_gfs()
    if not date_str:
        print("   !! Aucun réseau GFS trouvé")
        return {}

    print(f"   Réseau : {date_str} {cycle:02d}h UTC")
    dossier = tempfile.mkdtemp()
    resultat = {}
    import xarray as xr

    try:
        for h in ECHEANCES:
            # On demande uniquement la CAPE à la surface pour notre zone
            url = (f"{GFS_BASE_URL}?file=gfs.t{cycle:02d}z.pgrb2.0p25.f{h:03d}"
                   f"&lev_surface=on&var_CAPE=on&subregion=&leftlon={LON_MIN}&rightlon={LON_MAX}&toplat={LAT_MAX}&bottomlat={LAT_MIN}"
                   f"&dir=%2Fgfs.{date_str}%2F{cycle:02d}%2Fatmos")
            
            chemin = os.path.join(dossier, f"gfs_{h}.grib2")
            try:
                r = requests.get(url, timeout=60)
                if r.status_code == 200 and len(r.content) > 1000:
                    with open(chemin, 'wb') as f:
                        f.write(r.content)
                    
                    ds = xr.open_dataset(chemin, engine="cfgrib")
                    val_vars = list(ds.data_vars)
                    if val_vars:
                        donnees = ds[val_vars[0]]
                        cellules = points_zone(ds.latitude.values, ds.longitude.values, donnees.values, mode="max")
                        resultat[h] = {"cape": cellules}
                        print(f"   H+{h} : {len(cellules)} points")
                    ds.close()
            except Exception as e:
                print(f"   !! Erreur GFS H+{h} : {e}")
    finally:
        shutil.rmtree(dossier, ignore_errors=True)

    return resultat

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
    now = datetime.now(timezone.utc)
    for recul_jours in range(2):
        jour = now - timedelta(days=recul_jours)
        date = jour.strftime("%Y%m%d")
        for cycle in ICON_CYCLES:
            if recul_jours == 0 and cycle > now.hour:
                continue
            url = f"{ICON_BASE}/{cycle:02d}/cape_ml/icon-d2_germany_regular-lat-lon_single-level_{date}{cycle:02d}_001_CAPE_ML.grib2.bz2"
            try:
                if requests.head(url, timeout=10).status_code == 200:
                    return date, cycle
            except:
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
            if chemin:
                try:
                    ds = xr.open_dataset(chemin, engine="cfgrib")
                    val = list(ds.data_vars)[0]
                    resultat[h] = {"cape": points_zone(ds.latitude.values, ds.longitude.values, ds[val].values, mode="max")}
                    ds.close()
                    print(f"   H+{h} : {len(resultat[h]['cape'])} points")
                except:
                    pass
    finally:
        shutil.rmtree(dossier, ignore_errors=True)
    return resultat

# ============================================================
# FUSION PESSIMISTE
# ============================================================
def compiler_points():
    # On utilise GFS au lieu d'AROME pour garantir un fonctionnement sans erreur
    d_gfs = telecharger_gfs()
    d_icon = telecharger_icon()

    print(">> Fusion pessimiste globale...")
    fusion = []

    for h in ECHEANCES:
        cellules = {}
        for source, src_nom in ((d_gfs, "GFS (NOAA)"), (d_icon, "ICON-D2")):
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
        "sources": ["GFS (NOAA)", "ICON-D2 (DWD)"],
        "previsions": fusion,
    }

    os.makedirs("public", exist_ok=True)
    chemin = os.path.join("public", "previsions_orages.json")
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False)
    print(f">> Fichier sauvegardé : {chemin}")

if __name__ == "__main__":
    main()