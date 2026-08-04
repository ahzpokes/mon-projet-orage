# ============================================================
# generer_meteo.py
# Télécharge AROME (Météo-France) et ICON-D2 (DWD),
# applique la fusion pessimiste, sauvegarde un JSON statique.
# ============================================================
import requests
import json
import os
import math
from datetime import datetime, timedelta, timezone

# ---------- CONFIGURATION ----------
# Zone couverte : France, Allemagne, Benelux, Suisse
LAT_MIN, LAT_MAX = 42.0, 55.5
LON_MIN, LON_MAX = -5.0, 16.0
GRILLE_PAS = 0.25          # Résolution de la grille de sortie (degrés)
NB_HEURES = 24             # Prévisions sur 24 heures

# API gratuite de Météo-France (AROME) - nécessite une clé gratuite
# sur https://portail-api.meteofrance.fr (inscription en 2 min)
CLE_METEO_FRANCE = os.environ.get("METEOFRANCE_API_KEY", "")

# ---------- 1. TÉLÉCHARGEMENT AROME ----------
def telecharger_arome():
    """Récupère le CAPE du modèle AROME via l'API Open Data Météo-France."""
    print(">> Téléchargement AROME...")
    # Si pas de clé API, on génère des données de démonstration
    if not CLE_METEO_FRANCE:
        print("   (Pas de clé API -> données de démonstration)")
        return generer_donnees_demo("AROME")
    # --- Version réelle (à activer avec ta clé) ---
    # url = "https://public-api.meteofrance.fr/public/arome/1.0/..."
    # reponse = requests.get(url, headers={"apikey": CLE_METEO_FRANCE})
    # ... décoder le GRIB ...
    return generer_donnees_demo("AROME")

# ---------- 2. TÉLÉCHARGEMENT ICON-D2 ----------
def telecharger_icon_d2():
    """Récupère le CAPE du modèle ICON-D2 via opendata.dwd.de (100% gratuit, sans clé)."""
    print(">> Téléchargement ICON-D2...")
    # Le DWD publie des fichiers GRIB2 ici :
    # https://opendata.dwd.de/weather/nwp/icon-d2/grib/
    # Exemple : 00/cape_ml/icon-d2_germany_regular-lat-lon_single-level_..._cape_ml.grib2.bz2
    # Pour la démo, on simule les données :
    return generer_donnees_demo("ICON-D2")

# ---------- DONNÉES DE DÉMONSTRATION ----------
def generer_donnees_demo(modele):
    """Génère une grille de CAPE réaliste pour tester l'interface."""
    grille = []
    # On crée 2-3 "foyers orageux" fictifs qui bougent avec le temps
    for heure in range(NB_HEURES):
        points = []
        # Foyer 1 : se déplace d'ouest en est sur la France
        c1_lat = 46.0 + 0.15 * heure * 0.1
        c1_lon = 0.0 + 0.35 * heure
        # Foyer 2 : sur l'Allemagne
        c2_lat = 50.5
        c2_lon = 8.0 + 0.2 * heure
        lat = LAT_MIN
        while lat <= LAT_MAX:
            lon = LON_MIN
            while lon <= LON_MAX:
                d1 = math.sqrt((lat - c1_lat)**2 + (lon - c1_lon)**2)
                d2 = math.sqrt((lat - c2_lat)**2 + (lon - c2_lon)**2)
                # CAPE simulé : gaussienne autour des foyers
                cape = 2500 * math.exp(-d1**2 / 1.5) + 1800 * math.exp(-d2**2 / 1.2)
                # Le "bruit" diffère selon le modèle pour tester la fusion
                if modele == "ICON-D2":
                    cape *= 1.15  # ICON-D2 un peu plus pessimiste
                else:
                    cape *= 0.9
                if cape > 100:  # On ne garde que ce qui est significatif
                    points.append({
                        "lat": round(lat, 3),
                        "lon": round(lon, 3),
                        "cape": round(cape),
                        "top_cb": calculer_top_cb(cape)
                    })
                lon += GRILLE_PAS
            lat += GRILLE_PAS
        grille.append({"heure": heure, "points": points})
    return grille

# ---------- 3. CALCUL DU TOP CB ----------
def calculer_top_cb(cape):
    """
    Estime le sommet des cumulonimbus (en niveau de vol FL)
    à partir de la CAPE. Formule simplifiée basée sur
    la température à 300/250/200 hPa (tropopause ~ FL340-FL380).
    """
    if cape < 500:
        return 0
    elif cape < 1500:
        return 250 + int((cape - 500) / 1000 * 50)   # FL250 -> FL300
    elif cape < 2500:
        return 300 + int((cape - 1500) / 1000 * 50)  # FL300 -> FL350
    else:
        return min(350 + int((cape - 2500) / 1000 * 30), 450)  # FL350+

# ---------- 4. FUSION PESSIMISTE ----------
def fusion_pessimiste(arome, icon):
    """Pour chaque heure et chaque point géographique, garde le pire des deux modèles."""
    print(">> Fusion pessimiste...")
    resultat = []
    for h in range(NB_HEURES):
        fusion = {}  # clé = (lat, lon)
        # On charge d'abord AROME
        for p in arome[h]["points"]:
            cle = (p["lat"], p["lon"])
            fusion[cle] = {**p, "modele": "AROME"}
        # Puis ICON-D2 : on écrase seulement si c'est PIRE
        for p in icon[h]["points"]:
            cle = (p["lat"], p["lon"])
            if cle not in fusion or p["cape"] > fusion[cle]["cape"]:
                fusion[cle] = {**p, "modele": "ICON-D2"}
        resultat.append({
            "heure": h,
            "points": list(fusion.values())
        })
    return resultat

# ---------- 5. SAUVEGARDE ----------
def main():
    arome = telecharger_arome()
    icon = telecharger_icon_d2()
    donnees = fusion_pessimiste(arome, icon)

    maintenant = datetime.now(timezone.utc)
    sortie = {
        "genere_le": maintenant.isoformat(),
        "heure_reference": maintenant.strftime("%Y-%m-%d %H:%M UTC"),
        "pas_horaire": 1,
        "previsions": donnees
    }

    os.makedirs("public", exist_ok=True)
    chemin = os.path.join("public", "previsions_orages.json")
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False)
    print(f">> Fichier sauvegardé : {chemin} ({os.path.getsize(chemin)//1024} Ko)")

if __name__ == "__main__":
    main()