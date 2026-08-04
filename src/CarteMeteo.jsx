import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { GeoJsonLayer } from "@deck.gl/layers";

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
      center: [5.5, 48.5],
      zoom: 5.2,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl(), "bottom-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-left");

    const overlay = new MapboxOverlay({
      interleaved: true,
      layers: [],
      getTooltip: ({ object }) => {
        if (!object) return null;
        onSurvol && onSurvol(object.properties);
        return null;
      },
    });
    map.addControl(overlay);

    mapRef.current = map;
    overlayRef.current = overlay;
    return () => map.remove();
  }, []);

  useEffect(() => {
    if (!overlayRef.current) return;
    const features = points
      .filter((p) => p.cape >= 500)
      .map((p) => {
        const taille = 0.125;
        return {
          type: "Feature",
          properties: p,
          geometry: {
            type: "Polygon",
            coordinates: [[
              [p.lon - taille, p.lat - taille],
              [p.lon + taille, p.lat - taille],
              [p.lon + taille, p.lat + taille],
              [p.lon - taille, p.lat + taille],
              [p.lon - taille, p.lat - taille],
            ]],
          },
        };
      });

    overlayRef.current.setProps({
      layers: [
        new GeoJsonLayer({
          id: "orages",
          data: { type: "FeatureCollection", features },
          filled: true,
          stroked: false,
          pickable: true,
          getFillColor: (f) => couleurCAPE(f.properties.cape),
          transitions: { getFillColor: 300 },
        }),
      ],
    });
  }, [points]);

  return <div ref={containerRef} className="carte-container" />;
}