import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "@fontsource-variable/bricolage-grotesque";
import "@fontsource-variable/instrument-sans";
import "@fontsource-variable/jetbrains-mono";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {/* Last resort: each panel and the console have their own boundary inside App. Reload = page reload. */}
    <ErrorBoundary name="The demo UI">
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
