import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
// On remplace GeoJsonLayer par HeatmapLayer
import { HeatmapLayer } from "@deck.gl/aggregation-layers"; 

export function couleurCAPE(cape) {
  if (cape < 500) return [0, 0, 0, 0];
  if (cape < 1500) return [255, 220, 50, 160];
  if (cape < 2500) return [255, 140, 0, 180];
  return [220, 50, 200, 200];
}

export function texteRisque(cape) {
  if (cape < 500) return "Négligeable";
  if (cape < 1500) return "Risque Modéré";
  if (cape < 2500) return "Risque Fort";
  return "Risque EXTRÊME";
}

export default function CarteMeteo({ points, onSurvol }) {
  const mapRef = useRef(null);
  const overlayRef = useRef(null);
  const containerRef = useRef(null);

  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
      center: [2.5, 46.5], // J'ai recentré sur la France
      zoom: 5.2,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl(), "bottom-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-left");

    const overlay = new MapboxOverlay({
      interleaved: true,
      layers: [],
    });
    map.addControl(overlay);

    mapRef.current = map;
    overlayRef.current = overlay;
    return () => map.remove();
  }, []);

  useEffect(() => {
    if (!overlayRef.current) return;
    
    // On ne garde que les points où il y a un risque d'orage
    const orages = points.filter((p) => p.cape >= 500);

    overlayRef.current.setProps({
      layers: [
        new HeatmapLayer({
          id: "orages-heatmap",
          data: orages,
          getPosition: d => [d.lon, d.lat],
          getWeight: d => d.cape,       // L'intensité définit la force de l'orage
          radiusPixels: 40,             // La taille du flou (à ajuster selon tes goûts !)
          intensity: 1.5,                 
          threshold: 0.01,
          colorRange: [
            [0, 0, 0, 0],               // Transparent pour les petits risques
            [255, 220, 50, 180],        // Jaune
            [255, 140, 0, 200],         // Orange
            [220, 50, 200, 220],        // Violet
            [255, 0, 0, 240]            // Rouge profond
          ],
          // onSurvol est un peu moins précis sur les heatmaps, on le garde si besoin
          pickable: true,
          onHover: ({ object }) => {
            if (object && onSurvol) onSurvol({ cape: object.weight, modele: "Mélange" });
            else if (!object && onSurvol) onSurvol(null);
          }
        }),
      ],
    });
  }, [points, onSurvol]);

  return <div ref={containerRef} className="carte-container" style={{width: '100%', height: '100vh'}} />;
}