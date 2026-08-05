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
  if (cape < 1500) return "Risque modéré";
  if (cape < 2500) return "Risque fort";
  return "Risque extrême";
}

export default function CarteMeteo({ points = [], onSurvol }) {
  const overlayRef = useRef(null);
  const containerRef = useRef(null);

  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
      center: [2.5, 46.5],
      zoom: 4.5,
      minZoom: 4.5,
      maxZoom: 4.5,
      scrollZoom: true,
      attributionControl: false,
    });

    map.addControl(
  new maplibregl.NavigationControl({
    showCompass: false,
  }),
  "bottom-right"
);

    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      "bottom-left"
    );

    const overlay = new MapboxOverlay({
      interleaved: false,
      layers: [],
    });

    map.addControl(overlay);
    overlayRef.current = overlay;

    return () => {
      overlayRef.current = null;
      map.remove();
    };
  }, []);

  useEffect(() => {
    if (!overlayRef.current) return;

    // Conversion stricte : évite les problèmes si cape/lat/lon viennent du JSON sous forme de texte.
    const orages = (Array.isArray(points) ? points : [])
      .map((point) => ({
        ...point,
        lon: Number(point.lon),
        lat: Number(point.lat),
        cape: Number(point.cape),
      }))
      .filter(
        (point) =>
          Number.isFinite(point.lon) &&
          Number.isFinite(point.lat) &&
          Number.isFinite(point.cape) &&
          point.cape >= 500
      );

    console.log("Points météo reçus :", points.length);
    console.log("Points orageux affichables :", orages.length);
    console.log("Premier point orageux :", orages[0]);

    overlayRef.current.setProps({
      layers: [
        new ContourLayer({
          id: "orages-contours",
          data: orages,
          getPosition: (d) => [d.lon, d.lat],
          getWeight: (d) => d.cape,

          // En mètres. 30 km rend les cellules assez jointives
          // pour former une nappe météo fluide.
          cellSize: 30000,
          aggregation: "MAX",
          gpuAggregation: true,

          // Une plage [min, max] = une nappe remplie (isobande).
          // Le dernier plafond est volontairement haut pour inclure
          // toutes les valeurs CAPE élevées.
          contours: [
            {
              threshold: [500, 1500],
              color: [255, 220, 50, 140],
              zIndex: 1,
            },
            {
              threshold: [1500, 2500],
              color: [255, 140, 0, 170],
              zIndex: 2,
            },
            {
              threshold: [2500, 10000],
              color: [220, 50, 200, 200],
              zIndex: 3,
            },
          ],
          pickable: false,
        }),

        // Couche invisible : elle sert uniquement au survol des données.
        new ScatterplotLayer({
          id: "orages-interactifs",
          data: orages,
          getPosition: (d) => [d.lon, d.lat],
          getRadius: 25000,
          radiusUnits: "meters",
          getFillColor: [0, 0, 0, 0],
          getLineColor: [0, 0, 0, 0],
          pickable: true,

          onHover: ({ object }) => {
            if (!onSurvol) return;

            onSurvol(
              object
                ? {
                    cape: object.cape,
                    top_cb: object.top_cb,
                    modele: object.modele,
                  }
                : null
            );
          },
        }),
      ],
    });
  }, [points, onSurvol]);

  return (
    <div
      ref={containerRef}
      className="carte-container"
      style={{ width: "100%", height: "100vh" }}
    />
  );
}