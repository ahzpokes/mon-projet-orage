import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ContourLayer } from "@deck.gl/aggregation-layers";

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
  const pointsOrageuxRef = useRef([]);
  const onSurvolRef = useRef(onSurvol);

  useEffect(() => {
    onSurvolRef.current = onSurvol;
  }, [onSurvol]);

  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
      center: [2.5, 46.5],
      zoom: 4.5,
      minZoom: 4.5,
      maxZoom: 4.5,
      scrollZoom: false,
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

    const gererSurvolCarte = (event) => {
      const pointsOrageux = pointsOrageuxRef.current;
      const callbackSurvol = onSurvolRef.current;

      if (!callbackSurvol || pointsOrageux.length === 0) {
        return;
      }

      const longitudeSouris = event.lngLat.lng;
      const latitudeSouris = event.lngLat.lat;

      let pointLePlusProche = null;
      let distanceLaPlusCourteKm = Infinity;

      for (const point of pointsOrageux) {
        const ecartLongitudeKm =
          (point.lon - longitudeSouris) *
          111.32 *
          Math.cos((latitudeSouris * Math.PI) / 180);

        const ecartLatitudeKm =
          (point.lat - latitudeSouris) * 111.32;

        const distanceKm = Math.sqrt(
          ecartLongitudeKm ** 2 + ecartLatitudeKm ** 2
        );

        if (distanceKm < distanceLaPlusCourteKm) {
          distanceLaPlusCourteKm = distanceKm;
          pointLePlusProche = point;
        }
      }

      // Les points de ta grille sont espacés d'environ 15 à 22 km.
      // Au-delà de 25 km, le curseur est considéré hors zone de données.
      if (pointLePlusProche && distanceLaPlusCourteKm <= 25) {
        callbackSurvol({
          cape: pointLePlusProche.cape,
          top_cb: pointLePlusProche.top_cb,
          modele: pointLePlusProche.modele,
        });
      } else {
        callbackSurvol(null);
      }
    };

    const quitterCarte = () => {
      if (onSurvolRef.current) {
        onSurvolRef.current(null);
      }
    };

    map.on("mousemove", gererSurvolCarte);
    containerRef.current.addEventListener("mouseleave", quitterCarte);

    return () => {
      map.off("mousemove", gererSurvolCarte);

      if (containerRef.current) {
        containerRef.current.removeEventListener("mouseleave", quitterCarte);
      }

      overlayRef.current = null;
      map.remove();
    };
  }, []);

  useEffect(() => {
    if (!overlayRef.current) return;

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

    pointsOrageuxRef.current = orages;

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
          cellSize: 30000,
          aggregation: "MAX",
          gpuAggregation: true,
          pickable: false,

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
        }),
      ],
    });
  }, [points]);

  return (
    <div
      ref={containerRef}
      className="carte-container"
      style={{ width: "100%", height: "100vh" }}
    />
  );
}
