import React, { useEffect, useState } from "react";

/**
 * Day/Night Theme Toggle
 * Switches between Day (light) and Night (dark) modes seamlessly.
 */
export default function ThemeToggle() {
  const [isNight, setIsNight] = useState(true);

  useEffect(() => {
    // Default to dark mode if not specified, matching mgeko default
    const saved = localStorage.getItem("theme");
    const currentIsNight = saved ? saved === "dark" : true;
    setIsNight(currentIsNight);
    applyMode(currentIsNight);
  }, []);

  const applyMode = (night) => {
    setIsNight(night);
    const themeVal = night ? "dark" : "light";
    localStorage.setItem("theme", themeVal);
    document.documentElement.setAttribute("data-theme", themeVal);
    if (night) {
      document.documentElement.classList.add("dark");
      document.body.classList.remove("light-mode");
    } else {
      document.documentElement.classList.remove("dark");
      document.body.classList.add("light-mode");
    }
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("theme-changed", { detail: themeVal }));
    }
  };

  const toggleTheme = () => {
    applyMode(!isNight);
  };

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className="p-1.5 rounded-lg text-gray-300 hover:text-[#00AEF0] hover:bg-[#15171c] transition flex items-center justify-center text-sm focus:outline-none"
      title={isNight ? "Switch to Day Mode (Light)" : "Switch to Night Mode (Dark)"}
      aria-label={isNight ? "Switch to Day Mode" : "Switch to Night Mode"}
    >
      {isNight ? (
        <span className="text-amber-400 text-sm leading-none flex items-center gap-1" title="Night mode active (click for Day mode)">
          <i className="fas fa-sun text-sm"></i>
        </span>
      ) : (
        <span className="text-blue-500 text-sm leading-none flex items-center gap-1" title="Day mode active (click for Night mode)">
          <i className="fas fa-moon text-sm"></i>
        </span>
      )}
    </button>
  );
}
