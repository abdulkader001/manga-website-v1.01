import { useEffect } from "react";
import { useLocation } from "react-router-dom";

/**
 * ScrollToTop Component
 * Ensures every page transition instantly resets the scroll position to the top,
 * preventing pages from opening scrolled down to the bottom.
 */
export default function ScrollToTop() {
  const { pathname, search } = useLocation();

  useEffect(() => {
    // Reset window scroll position instantly on any route or search param change
    window.scrollTo({
      top: 0,
      left: 0,
      behavior: "instant",
    });

    // Also reset document scrolling elements
    if (document.documentElement) {
      document.documentElement.scrollTop = 0;
    }
    if (document.body) {
      document.body.scrollTop = 0;
    }
  }, [pathname, search]);

  return null;
}
