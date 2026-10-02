import React, { useEffect, useState } from "react";
import { apiFetch } from "../services/api";

// Geolock: when the server answers 451 REGION_BLOCKED (the visitor's country
// is blocked by the main admin), show a plain notice instead of a broken site.
// Normal visitors see the site at once; the check runs in the background.

export const REGION_BLOCKED_EVENT = "region-blocked";

export function RegionBlocked() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0b0d10] p-6 text-center">
      <div className="max-w-md space-y-3">
        <div className="text-5xl" aria-hidden="true">
          🌐
        </div>
        <h1 className="text-xl font-bold text-white">Not available in your country</h1>
        <p className="text-sm text-[#8b93a3]">This site isn&apos;t available where you are.</p>
        <p className="text-[10px] text-[#5b6372]">
          <a href="https://db-ip.com" target="_blank" rel="noopener noreferrer" className="underline">
            IP Geolocation by DB-IP
          </a>
        </p>
      </div>
    </div>
  );
}

export default function RegionGate({ children }) {
  const [blocked, setBlocked] = useState(false);

  useEffect(() => {
    let alive = true;
    const onBlocked = () => setBlocked(true);
    window.addEventListener(REGION_BLOCKED_EVENT, onBlocked);
    apiFetch("/geo/status")
      .then((res) => {
        if (alive && res.status === 451) setBlocked(true);
      })
      .catch(() => {
        // Network trouble is not a country block.
      });
    return () => {
      alive = false;
      window.removeEventListener(REGION_BLOCKED_EVENT, onBlocked);
    };
  }, []);

  return blocked ? <RegionBlocked /> : children;
}
