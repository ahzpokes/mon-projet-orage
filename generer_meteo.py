import os
import bz2
import glob
import json
import warnings
import requests
import numpy as np
import pandas as pd
import xarray as xr
from datetime import datetime, timedelta, timezone

# Masquer les warnings de cfgrib
warnings.filterwarnings("ignore", message="Ignoring index file")

# --- CONFIGURATION ---
DOSSIER_TMP = "./tmp_icon"
FICHIER_SORTIE = "public/previsions_orages.json"

# Boîte englobante France métropolitaine élargie (Corse incluse)
LAT_MIN, LAT_MAX = 41.0, 51.5
LON_MIN, LON_MAX = -5.5, 9.5

# Seuils de détection Convective / CB
SEUIL_CAPE_MIN = 500  # J/kg
SEUIL_CIN_MAX = 50    # J/kg (Rappel: CIN ICON est positive)

# Echéances à récupérer (comme dans ton filtre ATFCM : 0 à 9h, puis 12, 15, 18, 21, 24h)
ECHEANCES_CIBLES = list(range(0, 10)) + [12, 15, 18, 21, 24]

def calculer_top_cb_realiste(cape: float) -> int:
    """Estimation aéronautique réaliste du Top CB (en Niveaux de Vol - FL)"""
    if cape < 500:
        return 0
    elif cape < 1000:
        fl_cape = 250 + ((cape - 500) / 500.0) * 70
    elif cape < 2500:
        fl_cape = 320 + ((cape - 1000) / 1500.0) * 70
    else:
        cape_plafond = min(cape, 4000)
        fl_cape = 390 + ((cape_plafond - 2500) / 1500.0) * 60
    return int(round(fl_cape / 10.0)) * 10

def nettoyer_fichiers_idx():
    """Supprime les fichiers .idx résiduels pour éviter les warnings."""
    for fichier in glob.glob(f"{DOSSIER_TMP}/*.idx"):
        try:
            os.remove(fichier)
        except:
            pass

def generer_url(run_dt: datetime, parametre: str, echeance: int) -> str:
    """Construit l'URL exacte vers opendata.dwd.de pour ICON-EU."""
    run_str = f"{run_dt.hour:02d}"
    date_str = run_dt.strftime("%Y%m%d%H")
    ech_str = f"{echeance:03d}"
    return f"https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run_str}/{parametre.lower()}/icon-eu_europe_regular-lat-lon_single-level_{date_str}_{ech_str}_{parametre.upper()}.grib2.bz2"

def trouver_dernier_run() -> datetime:
    """Trouve le dernier run ICON-EU publié (par pas de 3h)."""
    maintenant = datetime.now(timezone.utc)
    heure_run = (maintenant.hour // 3) * 3
    run_test = maintenant.replace(hour=heure_run, minute=0, second=0, microsecond=0)
    
    print(">> Recherche du dernier run ICON-EU disponible...")
    for _ in range(8):
        # On teste l'échéance 0 qui est toujours la première publiée
        url = generer_url(run_test, "CAPE_ML", 0)
        print(f"   Test du run {run_test.strftime('%H')}Z...")
        
        try:
            reponse = requests.get(url, stream=True, timeout=5)
            code = reponse.status_code
            reponse.close()
            
            if code == 200:
                print(f"   -> Run {run_test.strftime('%H')}Z trouvé !")
                return run_test
        except requests.RequestException:
            pass
            
        run_test -= timedelta(hours=3)
        
    raise Exception("Impossible de trouver un run récent sur les dernières 24h.")

def telecharger_et_decompresser(url: str, chemin_dest: str) -> bool:
    """Télécharge et décompresse. Retourne True si succès, False si 404."""
    reponse = requests.get(url)
    if reponse.status_code == 404:
        return False
    reponse.raise_for_status() 
    with open(chemin_dest, "wb") as f:
        f.write(bz2.decompress(reponse.content))
    return True

def extraire_points_orages(fichier_cape: str, fichier_cin: str) -> list:
    """Ouvre les GRIB2, filtre sur la France, applique les seuils et retourne la liste des points."""
    ds_cape = xr.open_dataset(fichier_cape, engine="cfgrib")
    ds_cin = xr.open_dataset(fichier_cin, engine="cfgrib")
    
    df_cape = ds_cape.to_dataframe().reset_index()
    df_cin = ds_cin.to_dataframe().reset_index()
    
    nom_var_cape = list(ds_cape.data_vars)[0]
    nom_var_cin = list(ds_cin.data_vars)[0]
    
    masque_geo = (
        (df_cape['latitude'] >= LAT_MIN) & (df_cape['latitude'] <= LAT_MAX) &
        (df_cape['longitude'] >= LON_MIN) & (df_cape['longitude'] <= LON_MAX)
    )
    
    df_final = pd.merge(
        df_cape[masque_geo][['latitude', 'longitude', nom_var_cape]],
        df_cin[masque_geo][['latitude', 'longitude', nom_var_cin]],
        on=['latitude', 'longitude']
    ).rename(columns={nom_var_cape: 'cape', nom_var_cin: 'cin'})
    
    # Nettoyage sentinelle CIN
    df_final.loc[df_final['cin'] < -900, 'cin'] = np.nan
    
    # Règle de détection Orages
    condition_cb = (df_final['cape'] >= SEUIL_CAPE_MIN) & \
                   ((df_final['cin'] <= SEUIL_CIN_MAX) | df_final['cin'].isna())
                   
    df_orages = df_final[condition_cb].copy()
    
    points = []
    for _, row in df_orages.iterrows():
        cape_val = int(row['cape'])
        cin_val = int(row['cin']) if pd.notna(row['cin']) else 0
        
        points.append({
            "lat": round(row['latitude'], 4),
            "lon": round(row['longitude'], 4),
            "cape": cape_val,
            "cin": cin_val,
            "top_cb": calculer_top_cb_realiste(cape_val),
            "modele": "ICON-EU"
        })
    
    return points

def main():
    os.makedirs(DOSSIER_TMP, exist_ok=True)
    os.makedirs(os.path.dirname(FICHIER_SORTIE) or ".", exist_ok=True)
    nettoyer_fichiers_idx()

    run_dt = trouver_dernier_run()
    
    orages_par_heure = {}
    pas_horaires_dispos = []
    
    print(f"\n>> Traitement des {len(ECHEANCES_CIBLES)} échéances ciblées...")
    
    for ech in ECHEANCES_CIBLES:
        print(f"\n--- Échéance H+{ech} ---")
        fichier_cape = os.path.join(DOSSIER_TMP, f"cape_ml_{ech:03d}.grib2")
        fichier_cin = os.path.join(DOSSIER_TMP, f"cin_ml_{ech:03d}.grib2")
        
        # Téléchargement
        url_cape = generer_url(run_dt, "CAPE_ML", ech)
        url_cin = generer_url(run_dt, "CIN_ML", ech)
        
        succes_cape = telecharger_et_decompresser(url_cape, fichier_cape)
        succes_cin = telecharger_et_decompresser(url_cin, fichier_cin)
        
        if not succes_cape or not succes_cin:
            print(f"   [!] Fichiers indisponibles pour H+{ech}, passage au suivant.")
            continue
            
        # Extraction
        points_orages = extraire_points_orages(fichier_cape, fichier_cin)
        print(f"   -> {len(points_orages)} cellules orageuses détectées.")
        
        if len(points_orages) > 0:
            orages_par_heure[ech] = points_orages
            pas_horaires_dispos.append(ech)
            
        nettoyer_fichiers_idx()

    print("\n>> Structuration au format historique...")
    
    previsions_liste = [{"heure": h, "points": orages_par_heure[h]} for h in pas_horaires_dispos]
    
    sortie = {
        "genere_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "heure_reference": run_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "run_modele": f"{run_dt.hour:02d}Z",
        "pas_horaires": pas_horaires_dispos,
        "previsions": previsions_liste,
        "source": "ICON-EU (via DWD Opendata direct)"
    }
    
    with open(FICHIER_SORTIE, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, indent=2)
        
    print(f"\n>> Fichier généré avec succès : {FICHIER_SORTIE}")

if __name__ == "__main__":
    main()