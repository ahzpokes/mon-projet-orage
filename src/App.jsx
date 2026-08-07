import { useEffect, useState } from "react";
import CarteMeteo, { couleurCAPE, texteRisque } from "./CarteMeteo";
import "./styles.css";

const ECHEANCES_PAR_DEFAUT = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
const VITESSE_LECTURE_MS = 1500;

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
        const echeances =
          Array.isArray(data.pas_horaires) && data.pas_horaires.length > 0
            ? data.pas_horaires
            : ECHEANCES_PAR_DEFAUT;

        const heureGeneration = new Date(data.genere_le);
        const maintenant = Date.now();

        // Recherche de l'échéance dont l'heure est la plus proche de maintenant.
        const indexLePlusProche = echeances.reduce(
          (meilleurIndex, echeance, index) => {
            const heureEcheance =
              heureGeneration.getTime() + Number(echeance) * 60 * 60 * 1000;

            const heureMeilleureEcheance =
              heureGeneration.getTime() +
              Number(echeances[meilleurIndex]) * 60 * 60 * 1000;

            const ecartActuel = Math.abs(heureEcheance - maintenant);
            const meilleurEcart = Math.abs(
              heureMeilleureEcheance - maintenant
            );

            return ecartActuel < meilleurEcart ? index : meilleurIndex;
          },
          0
        );

        setDonnees(data);
        setIndexHeure(indexLePlusProche);
        setChargement(false);
      })
      .catch((err) => {
        setErreur(err.message);
        setChargement(false);
      });
  }, []);

  useEffect(() => {
    if (!lectureActive || !donnees) return undefined;

    const echeances =
      Array.isArray(donnees.pas_horaires) && donnees.pas_horaires.length > 0
        ? donnees.pas_horaires
        : ECHEANCES_PAR_DEFAUT;

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

  const echeances =
    Array.isArray(donnees.pas_horaires) && donnees.pas_horaires.length > 0
      ? donnees.pas_horaires
      : ECHEANCES_PAR_DEFAUT;

  const echeanceCourante = echeances[indexHeure];
  const previsions = donnees.previsions || [];

  const donneesCourantes = previsions.find(
    (prevision) => Number(prevision.heure) === Number(echeanceCourante)
  );

  const pointsActuels = donneesCourantes?.points || [];
  const heureRef = new Date(donnees.genere_le);

  const heureAffichee = new Date(
    heureRef.getTime() + Number(echeanceCourante) * 60 * 60 * 1000
  );

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
            Actualisé à :{" "}
            {heureRef.toLocaleTimeString("fr-FR", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </p>
      </div>

      <div className="legende">
        <h3>Risque (CAPE)</h3>

        <div className="legende-item">
          <div
            className="legende-couleur"
            style={{ background: "rgb(255,220,50)" }}
          />
          <span>Modéré · 500–1500</span>
        </div>

        <div className="legende-item">
          <div
            className="legende-couleur"
            style={{ background: "rgb(255,140,0)" }}
          />
          <span>Fort · 1500–2500</span>
        </div>

        <div className="legende-item">
          <div
            className="legende-couleur"
            style={{ background: "rgb(220,50,200)" }}
          />
          <span>Extrême · &gt; 2500</span>
        </div>
      </div>

      {tooltip && (
        <div
          className="tooltip-meteo"
          style={{
            position: "absolute",
            bottom: 120,
            left: 20,
            zIndex: 20,
          }}
        >
          <div
            className="risque"
            style={{
              color: `rgb(${couleurCAPE(tooltip.cape)
                .slice(0, 3)
                .join(",")})`,
            }}
          >
            {texteRisque(tooltip.cape)}
          </div>

          <div>CAPE : {tooltip.cape} J/kg</div>
          <div>Top CB : FL{tooltip.top_cb}</div>
          <div style={{ color: "#a0b0d0" }}>
            Modèle retenu : {tooltip.modele}
          </div>
        </div>
      )}

      <div className="timeline">
        <div className="timeline-label">
          <span>
            Réf.{" "}
            {heureRef.toLocaleTimeString("fr-FR", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>

          <span className="heure-actuelle">
            {heureAffichee.toLocaleDateString("fr-FR", {
              weekday: "short",
            })}{" "}
            {heureAffichee.toLocaleTimeString("fr-FR", {
              hour: "2-digit",
              minute: "2-digit",
            })}{" "}
            (H+{echeanceCourante})
          </span>

          <span>H+{echeances[echeances.length - 1]}</span>
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "10px",
          }}
        >
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
            {lectureActive ? "❚❚" : "▶"}
          </button>

          <input
            type="range"
            min={0}
            max={echeances.length - 1}
            value={indexHeure}
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
                  index === 0 ||
                  index === echeances.length - 1 ||
                  heure === 12
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
