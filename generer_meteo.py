import os
import bz2
import glob
import json
import warnings
import requests
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
SEUIL_CAPE_MIN = 500      # J/kg
SEUIL_CIN_MAX = 50        # J/kg (CIN ICON : positif, sentinelle -999.9 = pas de parcelle convective)
SEUIL_HTOP_CON_MIN = 2500 # m : convection profonde uniquement (élimine la convection peu profonde)

# Échéances à récupérer (filtre ATFCM : 0 à 9h, puis 12, 15, 18, 21, 24h)
# Note : ICON-EU tourne toutes les 3h (00/03/06/.../21Z).
# Les runs intermédiaires 03/09/15/21Z ne publient que jusqu'à ~+30h :
# nos échéances (max +24h) restent couvertes.
ECHEANCES_CIBLES = list(range(0, 19)) # [0, 1, 2, ..., 18]

# Paramètres GRIB à télécharger.
# HTOP_CON = sommet du nuage convectif calculé par le modèle : c'est le "déclencheur"
# qui distingue l'instabilité potentielle (CAPE/CIN) de la convection réellement déclenchée.
PARAMETRES = ["CAPE_ML", "CIN_ML", "HTOP_CON"]

TIMEOUT_HTTP = 30  # secondes


def calculer_top_cb_empirique(cape: float) -> int:
    """Estimation empirique du Top CB (FL) à partir de la CAPE.
    Utilisée en SECOURS uniquement si HTOP_CON est indisponible pour une échéance."""
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


def top_cb_depuis_htop(htop_m: float) -> int:
    """Convertit le sommet convectif du modèle (mètres) en Niveau de Vol, arrondi au FL10."""
    if htop_m <= 0:
        return 0
    fl = (htop_m * 3.28084) / 100.0  # m -> ft -> FL
    return int(round(fl / 10.0)) * 10


def nettoyer_fichiers_tmp():
    """Supprime les fichiers .grib2 et .idx résiduels."""
    for fichier in glob.glob(f"{DOSSIER_TMP}/*.idx") + glob.glob(f"{DOSSIER_TMP}/*.grib2"):
        try:
            os.remove(fichier)
        except OSError:
            pass


def generer_url(run_dt: datetime, parametre: str, echeance: int) -> str:
    """Construit l'URL exacte vers opendata.dwd.de pour ICON-EU."""
    run_str = f"{run_dt.hour:02d}"
    date_str = run_dt.strftime("%Y%m%d%H")
    ech_str = f"{echeance:03d}"
    return (
        f"https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run_str}/{parametre.lower()}"
        f"/icon-eu_europe_regular-lat-lon_single-level_{date_str}_{ech_str}_{parametre.upper()}.grib2.bz2"
    )


def trouver_dernier_run() -> datetime:
    """Trouve le dernier run ICON-EU publié (cycles toutes les 3h)."""
    maintenant = datetime.now(timezone.utc)
    heure_run = (maintenant.hour // 3) * 3
    run_test = maintenant.replace(hour=heure_run, minute=0, second=0, microsecond=0)

    print(">> Recherche du dernier run ICON-EU disponible...")
    for _ in range(8):
        # On teste l'échéance 0 qui est toujours la première publiée
        url = generer_url(run_test, "CAPE_ML", 0)
        print(f"   Test du run {run_test.strftime('%H')}Z...")

        try:
            reponse = requests.get(url, stream=True, timeout=TIMEOUT_HTTP)
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
    """Télécharge et décompresse. True si succès, False si 404, exception sinon."""
    reponse = requests.get(url, timeout=TIMEOUT_HTTP)
    if reponse.status_code == 404:
        return False
    reponse.raise_for_status()
    with open(chemin_dest, "wb") as f:
        f.write(bz2.decompress(reponse.content))
    return True


def charger_grille_france(fichier: str) -> pd.DataFrame:
    """Ouvre un GRIB2, filtre sur la bbox France (optimisé RAM : filtrage xarray
    AVANT conversion pandas) et convertit les longitudes en -180/+180.
    Retourne un DataFrame [latitude, longitude, <nom_variable>]."""
    ds = xr.open_dataset(fichier, engine="cfgrib")
    nom_var = list(ds.data_vars)[0]

    # Filtrage en coordonnées NATIVES 0-360 (triées, sans discontinuité au méridien).
    # La bbox France -5.5/+9.5 devient deux intervalles : [354.5, 360] et [0, 9.5].
    mask = (
        (ds['latitude'] >= LAT_MIN) & (ds['latitude'] <= LAT_MAX) &
        (
            ((ds['longitude'] >= 360 + LON_MIN) & (ds['longitude'] <= 360)) |
            ((ds['longitude'] >= 0) & (ds['longitude'] <= LON_MAX))
        )
    )
    df = ds.where(mask, drop=True).to_dataframe().reset_index()
    df = df.dropna(subset=[nom_var])

    # Conversion en -180/+180 APRÈS le filtrage (sûr sur un DataFrame)
    df['longitude'] = ((df['longitude'] + 180) % 360) - 180

    return df[['latitude', 'longitude', nom_var]]


def extraire_points_orages(fichiers: dict) -> list:
    """Croise CAPE, CIN et HTOP_CON sur la France et retourne les cellules CB détectées.
    fichiers = {"CAPE_ML": chemin, "CIN_ML": chemin, "HTOP_CON": chemin ou None}"""
    df_cape = charger_grille_france(fichiers["CAPE_ML"])
    df_cin = charger_grille_france(fichiers["CIN_ML"])

    df_cape = df_cape.rename(columns={df_cape.columns[2]: 'cape'})
    df_cin = df_cin.rename(columns={df_cin.columns[2]: 'cin'})

    df_final = pd.merge(df_cape, df_cin, on=['latitude', 'longitude'])

    htop_disponible = fichiers.get("HTOP_CON") is not None
    if htop_disponible:
        df_htop = charger_grille_france(fichiers["HTOP_CON"])
        df_htop = df_htop.rename(columns={df_htop.columns[2]: 'htop_con'})
        df_final = pd.merge(df_final, df_htop, on=['latitude', 'longitude'])
    else:
        print("   [!] HTOP_CON indisponible : détection CAPE/CIN seuls "
              "(faux positifs possibles), tops empiriques.")

    # Sentinelle CIN DWD : -999.9 = aucune parcelle convective trouvée => point exclu
    df_final = df_final[df_final['cin'] > -900]

    # Règle de détection CB
    condition_cb = (df_final['cape'] >= SEUIL_CAPE_MIN) & (df_final['cin'] <= SEUIL_CIN_MAX)
    if htop_disponible:
        # Le modèle doit avoir RÉELLEMENT déclenché de la convection profonde
        condition_cb &= (df_final['htop_con'] >= SEUIL_HTOP_CON_MIN)

    df_orages = df_final[condition_cb].copy()

    # Top CB : priorité au sommet convectif du modèle, sinon formule empirique CAPE
    if htop_disponible:
        df_orages['top_cb'] = df_orages['htop_con'].map(top_cb_depuis_htop)
    else:
        df_orages['top_cb'] = df_orages['cape'].map(calculer_top_cb_empirique)

    # Construction vectorisée (évite iterrows, lent sur des milliers de points)
    df_orages['lat'] = df_orages['latitude'].round(4)
    df_orages['lon'] = df_orages['longitude'].round(4)
    df_orages['cape'] = df_orages['cape'].astype(int)
    df_orages['cin'] = df_orages['cin'].astype(int)
    df_orages['modele'] = "ICON-EU"

    return df_orages[['lat', 'lon', 'cape', 'cin', 'top_cb', 'modele']].to_dict('records')


def ecrire_json_atomique(sortie: dict, chemin: str):
    """Écrit dans un fichier temporaire puis remplace atomiquement le fichier cible.
    Évite que le frontend lise un JSON tronqué pendant l'écriture."""
    chemin_tmp = chemin + ".tmp"
    with open(chemin_tmp, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, indent=2)
    os.replace(chemin_tmp, chemin)


def main():
    os.makedirs(DOSSIER_TMP, exist_ok=True)
    os.makedirs(os.path.dirname(FICHIER_SORTIE) or ".", exist_ok=True)
    nettoyer_fichiers_tmp()

    run_dt = trouver_dernier_run()

    orages_par_heure = {}
    pas_horaires_dispos = []
    echeances_manquantes = []

    print(f"\n>> Traitement des {len(ECHEANCES_CIBLES)} échéances ciblées...")

    for ech in ECHEANCES_CIBLES:
        print(f"\n--- Échéance H+{ech} ---")

        # Téléchargement de tous les paramètres
        fichiers = {}
        erreur_fatale = False
        for param in PARAMETRES:
            chemin = os.path.join(DOSSIER_TMP, f"{param.lower()}_{ech:03d}.grib2")
            url = generer_url(run_dt, param, ech)
            try:
                succes = telecharger_et_decompresser(url, chemin)
            except requests.RequestException as e:
                print(f"   [!] Erreur réseau {param} H+{ech} : {e}")
                succes = False

            if not succes:
                if param == "HTOP_CON":
                    # HTOP_CON manquant : on continue en mode dégradé (CAPE/CIN seuls)
                    fichiers[param] = None
                else:
                    # CAPE ou CIN manquant : échéance inexploitable
                    print(f"   [!] {param} indisponible pour H+{ech} (run intermédiaire ?), "
                          f"passage au suivant.")
                    erreur_fatale = True
                    break
            else:
                fichiers[param] = chemin

        if erreur_fatale:
            echeances_manquantes.append(ech)
            continue

        points_orages = extraire_points_orages(fichiers)
        print(f"   -> {len(points_orages)} cellules CB détectées.")

        if len(points_orages) > 0:
            orages_par_heure[ech] = points_orages
            pas_horaires_dispos.append(ech)

    nettoyer_fichiers_tmp()

    if echeances_manquantes:
        print(f"\n>> Échéances manquantes : {echeances_manquantes}")

    print("\n>> Structuration au format historique...")

    previsions_liste = []
    for h in pas_horaires_dispos:
        validite = run_dt + timedelta(hours=h)
        previsions_liste.append({
            "heure": h,                                                    # offset H+n (compatibilité frontend)
            "validite_utc": validite.strftime("%Y-%m-%dT%H:%M:%SZ"),       # heure de validité en TU
            "points": orages_par_heure[h]
        })

    sortie = {
        "genere_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "heure_reference": run_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_modele": f"{run_dt.hour:02d}Z",
        "timezone": "UTC",
        "pas_horaires": pas_horaires_dispos,
        "echeances_manquantes": echeances_manquantes,
        "previsions": previsions_liste,
        "source": "ICON-EU (via DWD Opendata direct)"
    }

    ecrire_json_atomique(sortie, FICHIER_SORTIE)

    print(f"\n>> Fichier généré avec succès : {FICHIER_SORTIE}")


if __name__ == "__main__":
    main()
