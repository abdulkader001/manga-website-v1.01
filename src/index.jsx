import React from "react";
import ReactDOM from "react-dom/client";
import App from "./app";
import { AuthProvider } from "./contexts/AuthContext";
import { installErrorReporter } from "./utils/errorReporter";
import "@fortawesome/fontawesome-free/css/all.min.css";
import "material-icons/iconfont/material-icons.css";
import "material-icons/iconfont/outlined.css";
import "./index.css";
import "./styles/mgeko.css";

// Apply initial theme BEFORE first paint (prefer stored, fallback to system)
(function bootstrapTheme() {
  try {
    const stored = localStorage.getItem("theme"); // "light" | "dark"
    const systemDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const theme = stored || (systemDark ? "dark" : "light");
    document.documentElement.setAttribute("data-theme", theme);
  } catch {
    document.documentElement.setAttribute("data-theme", "light");
  }
})();

// Script errors and unhandled promise failures go to Admin -> Error Report.
installErrorReporter();

const root = ReactDOM.createRoot(document.getElementById("root"));
root.render(
  <React.StrictMode>
   <AuthProvider>
      <App />
    </AuthProvider>
  </React.StrictMode>
);

// Register PWA Service Worker for offline chapter caching
if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.warn("[PWA ServiceWorker] Registration notice:", err);
    });
  });
}
