import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ContourLayer } from "@deck.gl/aggregation-layers"; 
import { ScatterplotLayer } from "@deck.gl/layers";

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
      zoom: 5.2,
      minZoom: 4.5,       
      maxZoom: 8.0,       
      scrollZoom: false,  
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
        new ContourLayer({
          id: "orages-contours",
          data: orages,
          getPosition: d => [d.lon, d.lat],
          getWeight: d => d.cape,
          
          // --- LES RÉGLAGES CLÉS POUR QUE LA NAPPE S'AFFICHE ---
          cellSize: 20000, // Taille de la maille (20km)
          radiusPixels: 40, // INDISPENSABLE : Rayon de lissage pour fusionner les points
          gpuAggregation: true,
          aggregation: 'MAX', // Conserve la pire CAPE de la zone
          // ----------------------------------------------------
          
          contours: [
            { lowerThreshold: 500, upperThreshold: 1500, color: [255, 220, 50, 160] },
            { lowerThreshold: 1500, upperThreshold: 2500, color: [255, 140, 0, 180] },
            { lowerThreshold: 2500, color: [220, 50, 200, 200] }
          ]
        }),
        
        new ScatterplotLayer({
          id: "orages-interactive",
          data: orages,
          getPosition: d => [d.lon, d.lat],
          getRadius: 15000, 
          getFillColor: [0, 0, 0, 0], 
          pickable: true,
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