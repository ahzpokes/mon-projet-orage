import os
import json
import time
from datetime import datetime, timezone
import requests

# --- CONFIGURATION ---
SEUIL_CAPE_ORAGE = 500
FICHIER_SORTIE = "public/previsions_orages.json"

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

def deduire_run(heure_utc: datetime) -> int:
    """Déduit le run de Météo-France (00Z, 03Z, ..., 21Z)"""
    return (heure_utc.hour - 4) // 3 * 3 % 24

def main():
    print(">> Génération de la grille très haute résolution (France étendue)...")
    lats = []
    lons = []

    for lat in range(4100, 5200, 20): 
        for lon in range(-500, 1000, 20): 
            lats.append(lat / 100.0)
            lons.append(lon / 100.0)

    print(f"   {len(lats)} points à analyser.")

    taille_lot = 800
    orages_par_heure = {}
    heure_reference_api = None
    maintenant = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    print(">> Interrogation de l'API Open-Meteo en mode POST...")

    i = 0
    lot_num = 1
    while i < len(lats):
        lot_lats = lats[i:i+taille_lot]
        lot_lons = lons[i:i+taille_lot]
        
        print(f"   Envoi du lot {lot_num} ({len(lot_lats)} points)...")
        
        # LE PAYLOAD QUI MARCHE (tiré de ton script d'origine)
        payload = {
            "latitude": lot_lats,
            "longitude": lot_lons,
            "hourly": ["cape"],
            "models": ["arome_france", "icon_d2"]
            "forecast_hours": 25,
            "timezone": "UTC"
        }
        
        try:
            reponse = requests.post("https://api.open-meteo.com/v1/forecast", json=payload, timeout=20)
            
            if reponse.status_code == 429:
                print("   [!] Limite atteinte (429). Pause de 60s...")
                time.sleep(60)
                continue
                
            if reponse.status_code != 200:
                print(f"   [!] Erreur HTTP {reponse.status_code} : {reponse.text}")
                i += taille_lot
                lot_num += 1
                continue
                
            donnees = reponse.json()
            if not isinstance(donnees, list):
                donnees = [donnees]
                
            for point in donnees:
                if "hourly" not in point:
                    continue
                    
                lat_pt = point["latitude"]
                lon_pt = point["longitude"]
                heures_iso = point["hourly"]["time"]
                
                if not heure_reference_api and len(heures_iso) > 0:
                    heure_reference_api = heures_iso[0].replace("T", " ") + ":00"

                cape_arome = point["hourly"].get("cape_arome_france", [])
                cape_icon = point["hourly"].get("cape_icon_d2", [])
                
                for idx_t, heure_str in enumerate(heures_iso):
                    dt_heure = datetime.strptime(heure_str, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
                    delta_heures = int((dt_heure - maintenant).total_seconds() / 3600)
                    
                    # FILTRE ATFCM : uniquement les heures utiles
                    if (0 <= delta_heures <= 9) or (12 <= delta_heures <= 24 and delta_heures % 3 == 0):
                        val_arome = cape_arome[idx_t] if (idx_t < len(cape_arome) and cape_arome[idx_t] is not None) else 0
                        val_icon = cape_icon[idx_t] if (idx_t < len(cape_icon) and cape_icon[idx_t] is not None) else 0
                        
                        max_cape = max(val_arome, val_icon)
                        
                        if max_cape >= SEUIL_CAPE_ORAGE:
                            if delta_heures not in orages_par_heure:
                                orages_par_heure[delta_heures] = []
                                
                            modele_dominant = "AROME" if val_arome >= val_icon else "ICON-D2"
                            
                            orages_par_heure[delta_heures].append({
                                "lat": lat_pt,
                                "lon": lon_pt,
                                "cape": round(max_cape),
                                "top_cb": calculer_top_cb_realiste(max_cape),
                                "modele": modele_dominant
                            })

            i += taille_lot
            lot_num += 1
            print("   (Pause de 90s pour respecter les limites...)")
            time.sleep(90)

        except Exception as e:
            print(f"   [!] Erreur de connexion : {e}")
            print("   Attente de 120s avant de continuer...")
            time.sleep(120)
            i += taille_lot

    print("\n>> Structuration au format historique...")

    pas_horaires_dispos = sorted(list(orages_par_heure.keys()))
    previsions_liste = [{"heure": h, "points": orages_par_heure[h]} for h in pas_horaires_dispos]

    run_calcule = deduire_run(datetime.now(timezone.utc))

    sortie = {
        "genere_le": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "heure_reference": heure_reference_api or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "run_modele": f"{run_calcule:02d}Z",
        "pas_horaires": pas_horaires_dispos,
        "previsions": previsions_liste,
        "source": "AROME / ICON-D2 (via Open-Meteo)"
    }

    os.makedirs(os.path.dirname(FICHIER_SORTIE) or ".", exist_ok=True)
    with open(FICHIER_SORTIE, "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, indent=2)

    print(f">> Fichier généré avec succès : {FICHIER_SORTIE}")

if __name__ == "__main__":
    main()