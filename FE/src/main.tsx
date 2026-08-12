/**
 * Punto de entrada del frontend React.
 * Monta la SPA, carga estilos globales y conecta el componente raíz con
 * el contenedor HTML provisto por Vite.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css";
import "nouislider/dist/nouislider.css";
import "./styles.css";
import { App } from "./App";

// Activa las comprobaciones adicionales de React en desarrollo y monta la SPA.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
