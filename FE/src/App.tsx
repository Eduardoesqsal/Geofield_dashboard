import { MapView } from "./components/MapView";

/**
 * Componente raíz de la SPA. La composición visual y el estado geoespacial se
 * delegan a `MapView` para mantener este punto de entrada deliberadamente fino.
 */
export function App() {
  return <MapView />;
}
