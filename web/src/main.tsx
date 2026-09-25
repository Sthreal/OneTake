async function cleanupLegacyMiniClawShell(): Promise<void> {
  if (typeof navigator === "undefined" || !("serviceWorker" in navigator)) return;
  try {
    const registrations = await navigator.serviceWorker.getRegistrations();
    if (registrations.length === 0) return;
    await Promise.all(registrations.map((registration) => registration.unregister()));
    if ("caches" in window) {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((key) => /miniclaw|onetake/i.test(key))
          .map((key) => caches.delete(key)),
      );
    }
    if (!sessionStorage.getItem("onetake-legacy-shell-cleaned")) {
      sessionStorage.setItem("onetake-legacy-shell-cleaned", "1");
      window.location.reload();
    }
  } catch {
    // The product shell has no service worker; cleanup is best-effort.
  }
}

void cleanupLegacyMiniClawShell();
import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);