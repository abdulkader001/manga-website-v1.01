import React, { useEffect, useState } from "react";

export default function AdblockCheck({ children }) {
  const [adblockDetected, setAdblockDetected] = useState(false);

  useEffect(() => {
    // Basic detection probe
    try {
      const testAd = document.createElement("div");
      testAd.innerHTML = "&nbsp;";
      testAd.className = "adsbox pub_300x250 pub_728x90 text-ad";
      testAd.style.position = "absolute";
      testAd.style.left = "-9999px";
      document.body.appendChild(testAd);

      window.setTimeout(() => {
        if (testAd.offsetHeight === 0) {
          setAdblockDetected(true);
        }
        testAd.remove();
      }, 200);
    } catch (e) {
      // Ignore detection probe errors
    }
  }, []);

  // Always render children so the application renders uninterrupted
  return <>{children}</>;
}
