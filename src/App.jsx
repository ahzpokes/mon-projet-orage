import { useEffect, useState } from "react";
import CarteMeteo, { couleurCAPE, texteRisque } from "./CarteMeteo";
import "./styles.css";

export default function App() {
  const [donnees, setDonnees] = useState(null);
  const [heure, setHeure] = useState(0);
  const [tooltip, setTooltip] = useState(null);
  const [chargement, setChargement] = useState(true);
  const [erreur, setErreur] = useState(null);

  // Chargement du JSON au démarrage
  useEffect(() => {
    fetch("/previsions_orages.json")
      .then((res) => {
        if (!res.ok) throw new Error("Fichier JSON introuvable");
        return res.json();
      })
      .then((data) => {
        setDonnees(data);
        setChargement(false);
      })
      .catch((err) => {
        setErreur(err.message);
        setChargement(false);
      });
  }, []);

  if (chargement) return <div className="titre-app"><h1>Chargement…</h1></div>;
  if (erreur) return <div className="titre-app"><h1>Erreur : {erreur}</h1><p>Vérifie que public/previsions_orages.json existe.</p></div>;

  const previsions = donnees.previsions;
  const pointsActuels = previsions[heure]?.points || [];

  // Calcul de l'heure réelle affichée
  const heureRef = new Date(donnees.genere_le);
  const heureAffichee = new Date(heureRef.getTime() + heure * 3600 * 1000);

  return (
    <>
      <CarteMeteo points={pointsActuels} onSurvol={setTooltip} />

      {/* Titre */}
      <div className="titre-app">
        <h1>⚡ Risque d'Orages — ATFCM</h1>
        <p>Généré le {donnees.heure_reference} · Fusion AROME + ICON-D2</p>
      </div>

      {/* Légende */}
      <div className="legende">
        <h3>Risque (CAPE)</h3>
        <div className="legende-item">
          <div className="legende-couleur" style={{ background: "rgb(255,220,50)" }} />
          <span>Modéré · 500–1500</span>
        </div>
        <div className="legende-item">
          <div className="legende-couleur" style={{ background: "rgb(255,140,0)" }} />
          <span>Fort · 1500–2500</span>
        </div>
        <div className="legende-item">
          <div className="legende-couleur" style={{ background: "rgb(220,50,200)" }} />
          <span>Extrême · &gt; 2500</span>
        </div>
      </div>

      {/* Tooltip au survol */}
      {tooltip && (
        <div className="tooltip-meteo" style={{ position: "absolute", bottom: 120, left: 20, zIndex: 20 }}>
          <div className="risque" style={{ color: `rgb(${couleurCAPE(tooltip.cape).slice(0,3).join(",")})` }}>
            {texteRisque(tooltip.cape)}
          </div>
          <div>CAPE : {tooltip.cape} J/kg</div>
          <div>Top CB : FL{tooltip.top_cb}</div>
          <div style={{ color: "#8b9dc3" }}>Modèle retenu : {tooltip.modele}</div>
        </div>
      )}

      {/* Timeline */}
      <div className="timeline">
        <div className="timeline-label">
          <span>Réf. {heureRef.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</span>
          <span className="heure-actuelle">
            {heureAffichee.toLocaleDateString("fr-FR", { weekday: "short" })}{" "}
            {heureAffichee.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
            {" "}(J+{heure}h)
          </span>
          <span>+{previsions.length - 1}h</span>
        </div>
        <input
          type="range"
          min={0}
          max={previsions.length - 1}
          value={heure}
          onChange={(e) => setHeure(Number(e.target.value))}
        />
      </div>
    </>
  );
}