import { useEffect, useState } from "react";
import CarteMeteo, { couleurCAPE, texteRisque } from "./CarteMeteo";
import "./styles.css";

export default function App() {
  const [donnees, setDonnees] = useState(null);
  const [indexHeure, setIndexHeure] = useState(0); // L'index du slider (0 à 13)
  const [tooltip, setTooltip] = useState(null);
  const [chargement, setChargement] = useState(true);
  const [erreur, setErreur] = useState(null);

  useEffect(() => {
    fetch("previsions_orages.json")
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
  if (erreur) return <div className="titre-app"><h1>Erreur : {erreur}</h1></div>;

  const echeances = donnees.pas_horaires || [1,2,3,4,5,6,7,8,9,12,15,18,21,24];
  const echeanceCourante = echeances[indexHeure];
  
  // Dans le nouveau format, le tableau previsions contient un objet par échéance
  const previsions = donnees.previsions || [];
  const donneesCourantes = previsions.find(p => p.heure === echeanceCourante);
  const pointsActuels = donneesCourantes ? donneesCourantes.points : [];

  const heureRef = new Date(donnees.genere_le);
  const heureAffichee = new Date(heureRef.getTime() + echeanceCourante * 3600 * 1000);

  return (
    <>
      <CarteMeteo points={pointsActuels} onSurvol={setTooltip} />

      <div className="titre-app">
        <h1>⚡ Risques Orage</h1>
        <p>Généré le {donnees.heure_reference}<br/>GFS / ICON-D2</p>
      </div>

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

      {tooltip && (
        <div className="tooltip-meteo" style={{ position: "absolute", bottom: 120, left: 20, zIndex: 20 }}>
          <div className="risque" style={{ color: `rgb(${couleurCAPE(tooltip.cape).slice(0, 3).join(",")})` }}>
            {texteRisque(tooltip.cape)}
          </div>
          <div>CAPE : {tooltip.cape} J/kg</div>
          <div>Top CB : FL{tooltip.top_cb}</div>
          <div style={{ color: "#a0b0d0" }}>Modèle retenu : {tooltip.modele}</div>
        </div>
      )}

      <div className="timeline">
        <div className="timeline-label">
          <span>Réf. {heureRef.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}</span>
          <span className="heure-actuelle">
            {heureAffichee.toLocaleDateString("fr-FR", { weekday: "short" })}{" "}
            {heureAffichee.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
            {" "}(H+{echeanceCourante})
          </span>
          <span>+24h</span>
        </div>
        <input
          type="range"
          min={0}
          max={echeances.length - 1}
          value={indexHeure}
          onChange={(e) => setIndexHeure(Number(e.target.value))}
        />
        {/* Affichage des petites graduations (ticks) */}
        <div style={{ display: "flex", justifyContent: "space-between", padding: "0 5px", marginTop: "4px", fontSize: "10px", color: "#666" }}>
          {echeances.map((h, i) => (
             <span key={i} style={{ visibility: (i===0 || i===echeances.length-1 || h===12) ? 'visible' : 'hidden' }}>H+{h}</span>
          ))}
        </div>
      </div>
    </>
  );
}
