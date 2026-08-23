import { useEffect, useState } from "react";
import CarteMeteo, { couleurCAPE, texteRisque } from "./CarteMeteo";
import "./styles.css";

const VITESSE_LECTURE_MS = 1500;
const HORIZON_MAX = 12; // Fenêtre tactique ATFCM : toujours jusqu'à H+12

// Formatage systématique en TU : timeZone "UTC" empêche le navigateur
// de convertir en heure locale (CEST = TU+2 en été).
const formaterTU = (date) =>
  date.toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }) + " TU";

const formaterJourTU = (date) =>
  date.toLocaleDateString("fr-FR", {
    weekday: "short",
    timeZone: "UTC",
  });

// Construit la liste des échéances du slider :
// - Début = échéance entière courante (on ne montre pas le passé)
// - Fin = toujours H+12 (fenêtre tactique fixe)
// - AUCUN filtrage sur les données : une échéance sans points = carte vide
//   ("pas de CB prévu"), ce qui est une information valide.
// Retourne [] si le run est trop vieux (> 12h) : données périmées.
const construireEcheances = (heureReference) => {
  const maintenant = Date.now();
  const echeanceActuelle = Math.floor(
    (maintenant - heureReference.getTime()) / (60 * 60 * 1000)
  );

  const debut = Math.max(0, echeanceActuelle);

  if (debut > HORIZON_MAX) {
    return []; // Run périmé : tout est dans le passé au-delà de H+12
  }

  return Array.from({ length: HORIZON_MAX - debut + 1 }, (_, i) => debut + i);
};

export default function App() {
  const [donnees, setDonnees] = useState(null);
  const [indexHeure, setIndexHeure] = useState(0);
  const [lectureActive, setLectureActive] = useState(false);
  const [tooltip, setTooltip] = useState(null);
  const [chargement, setChargement] = useState(true);
  const [erreur, setErreur] = useState(null);

  useEffect(() => {
    fetch("previsions_orages.json")
      .then((res) => {
        if (!res.ok) {
          throw new Error("Fichier JSON introuvable");
        }
        return res.json();
      })
      .then((data) => {
        // Référence = heure du RUN modèle (heure_reference), pas l'heure
        // d'exécution du script (genere_le), sinon les H+n sont décalés.
        const heureReference = new Date(data.heure_reference || data.genere_le);
        const echeances = construireEcheances(heureReference);

        setDonnees(data);
        setIndexHeure(0); // La première échéance = maintenant (début de fenêtre)
        setChargement(false);
      })
      .catch((err) => {
        setErreur(err.message);
        setChargement(false);
      });
  }, []);

  useEffect(() => {
    if (!lectureActive || !donnees) return undefined;

    const heureReference = new Date(donnees.heure_reference || donnees.genere_le);
    const echeances = construireEcheances(heureReference);

    if (echeances.length === 0) return undefined;

    const intervalle = window.setInterval(() => {
      setIndexHeure((indexActuel) =>
        indexActuel >= echeances.length - 1 ? 0 : indexActuel + 1
      );
    }, VITESSE_LECTURE_MS);

    // Arrête proprement le minuteur lors d'une pause ou de la fermeture du composant.
    return () => window.clearInterval(intervalle);
  }, [lectureActive, donnees]);

  if (chargement) {
    return (
      <div className="titre-app">
        <h1>Chargement…</h1>
      </div>
    );
  }

  if (erreur) {
    return (
      <div className="titre-app">
        <h1>Erreur : {erreur}</h1>
      </div>
    );
  }

  const heureRef = new Date(donnees.heure_reference || donnees.genere_le);
  const echeances = construireEcheances(heureRef);

  // Run périmé : toutes les échéances de la fenêtre 0-12h sont dans le passé
  if (echeances.length === 0) {
    return (
      <div className="titre-app">
        <h1>Données périmées</h1>
        <p>
          Le run {donnees.run_modele || "N/A"} date de plus de {HORIZON_MAX}h.
          Relancez le script de génération.
        </p>
      </div>
    );
  }

  // Sécurise l'index si la fenêtre a rétréci entre deux rendus
  const indexSur = Math.min(indexHeure, echeances.length - 1);
  const echeanceCourante = echeances[indexSur];

  const previsions = donnees.previsions || [];
  const donneesCourantes = previsions.find(
    (prevision) => Number(prevision.heure) === Number(echeanceCourante)
  );

  // Échéance sans données : carte vide (pas de CB prévu à cette heure).
  const echeanceManquante =
    Array.isArray(donnees.echeances_manquantes) &&
    donnees.echeances_manquantes.map(Number).includes(Number(echeanceCourante));
  const pointsActuels = donneesCourantes?.points ?? [];

  // Heure de validité : priorité au champ validite_utc du JSON,
  // sinon calcul depuis l'heure du run + échéance.
  const heureAffichee = donneesCourantes?.validite_utc
    ? new Date(donneesCourantes.validite_utc)
    : new Date(heureRef.getTime() + Number(echeanceCourante) * 60 * 60 * 1000);

  const changerHeure = (nouvelIndex) => {
    setLectureActive(false);
    setIndexHeure(Number(nouvelIndex));
  };

  return (
    <>
      <CarteMeteo points={pointsActuels} onSurvol={setTooltip} />

      <div className="titre-app">
        <h1>Risques Orage</h1>
        <p>
          Modèles : <strong>{donnees.source || "AROME / ICON-D2"}</strong>
          <br />
          Basé sur le Run : <strong>{donnees.run_modele || "N/A"}</strong>
          <br />
          <span style={{ fontSize: "0.85em", color: "#666" }}>
            Actualisé à {formaterTU(new Date(donnees.genere_le))}
          </span>
        </p>
      </div>

      <div className="legende">
        <h3>Risque CAPE</h3>
        <div className="legende-item">
          <div
            className="legende-couleur"
            style={{ background: "rgb(255,220,50)" }}
          />
          <span>Modéré 500–1500</span>
        </div>
        <div className="legende-item">
          <div
            className="legende-couleur"
            style={{ background: "rgb(255,140,0)" }}
          />
          <span>Fort 1500–2500</span>
        </div>
        <div className="legende-item">
          <div
            className="legende-couleur"
            style={{ background: "rgb(220,50,200)" }}
          />
          <span>Extrême &gt; 2500</span>
        </div>
      </div>

      {tooltip && (
        <div
          className="tooltip-meteo"
          style={{ position: "absolute", bottom: 120, left: 20, zIndex: 20 }}
        >
          <div
            className="risque"
            style={{
              color: `rgb(${couleurCAPE(tooltip.cape).slice(0, 3).join(",")})`,
            }}
          >
            {texteRisque(tooltip.cape)}
          </div>
          <div>CAPE : {tooltip.cape} J/kg</div>
          <div>Top CB : FL{tooltip.top_cb}</div>
          <div style={{ color: "#a0b0d0" }}>Modèle retenu : {tooltip.modele}</div>
        </div>
      )}

      <div className="timeline">
        <div className="timeline-label">
          <span>Réf. {formaterTU(heureRef)}</span>
          <span className="heure-actuelle">
            {formaterJourTU(heureAffichee)} {formaterTU(heureAffichee)} (H+
            {echeanceCourante})
            {echeanceManquante && (
              <span style={{ color: "#d97706" }}> — données indisponibles</span>
            )}
          </span>
          <span>+{HORIZON_MAX}h</span>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <button
            type="button"
            onClick={() => setLectureActive((active) => !active)}
            aria-label={
              lectureActive
                ? "Mettre l'animation en pause"
                : "Lancer l'animation"
            }
            style={{
              minWidth: "42px",
              height: "32px",
              border: "1px solid #5f82b8",
              borderRadius: "5px",
              background: lectureActive ? "#d97706" : "#1d4ed8",
              color: "#fff",
              fontSize: "16px",
              cursor: "pointer",
            }}
          >
            {lectureActive ? "⏸" : "▶"}
          </button>

          <input
            type="range"
            min={0}
            max={echeances.length - 1}
            value={indexSur}
            onChange={(e) => changerHeure(e.target.value)}
            style={{ flex: 1 }}
          />
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            padding: "0 5px 0 52px",
            marginTop: "4px",
            fontSize: "10px",
            color: "#666",
          }}
        >
          {echeances.map((heure, index) => (
            <span
              key={heure}
              style={{
                visibility:
                  index === 0 || index === echeances.length - 1 || heure === 12
                    ? "visible"
                    : "hidden",
              }}
            >
              H+{heure}
            </span>
          ))}
        </div>
      </div>
    </>
  );
}
