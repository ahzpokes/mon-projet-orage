import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { HeatmapLayer } from "@deck.gl/aggregation-layers"; 
import { ScatterplotLayer } from "@deck.gl/layers"; // <-- Ajout de cette ligne !

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
      center: [2.5, 46.5],
      zoom: 4,
	  // -- Les nouvelles restrictions de zoom --
      minZoom: 4,       // Empêche de voir le monde entier
      maxZoom: 4.8,       // Empêche de zoomer jusqu'aux rues
      scrollZoom: false,  // Désactive le zoom avec la molette de la souris (très utile)
      dragRotate: false,  // (Optionnel) Met à "false" si tu veux empêcher le glisser/déplacer
      // ----------------------------------------
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
    
    const orages = points.filter((p) => p.cape >= 500);

    overlayRef.current.setProps({
      layers: [
        // 1. La belle carte de chaleur visuelle (qui ne s'occupe plus de la souris)
        new HeatmapLayer({
          id: "orages-heatmap",
          data: orages,
          getPosition: d => [d.lon, d.lat],
          getWeight: d => d.cape,
          radiusPixels: 40,
          intensity: 1.5,                 
          threshold: 0.01,
          pickable: false, // <-- Désactivé ici
          colorRange: [
            [0, 0, 0, 0],
            [255, 220, 50, 180],
            [255, 140, 0, 200],
            [220, 50, 200, 220],
            [255, 0, 0, 240]
          ],
        }),
        // 2. La couche invisible qui attrape la souris et te rend le Top CB !
        new ScatterplotLayer({
          id: "orages-interactive",
          data: orages,
          getPosition: d => [d.lon, d.lat],
          getRadius: 15000, // Rayon de capture de la souris (en mètres)
          getFillColor: [0, 0, 0, 0], // Totalement transparent !
          pickable: true, // <-- C'est elle qui gère le Tooltip
          onHover: ({ object }) => {
            if (object && onSurvol) {
              onSurvol({ 
                cape: object.cape, 
                top_cb: object.top_cb, 
                modele: object.modele 
              });
            } else if (!object && onSurvol) {
              onSurvol(null);
            }
          }
        }),
      ],
    });
  }, [points, onSurvol]);

  return <div ref={containerRef} className="carte-container" style={{width: '100%', height: '100vh'}} />;
}