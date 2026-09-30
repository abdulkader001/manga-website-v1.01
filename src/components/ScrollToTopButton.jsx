import React, { useState, useEffect } from "react";

export default function ScrollToTopButton() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      // Show when scrolled down
      if (window.scrollY > 150) {
        setVisible(true);
      } else {
        setVisible(false);
      }
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();

    return () => {
      window.removeEventListener("scroll", handleScroll);
    };
  }, []);

  const scrollToTop = () => {
    window.scrollTo({
      top: 0,
      behavior: "smooth",
    });
  };

  if (!visible) return null;

  return (
    <button
      type="button"
      onClick={scrollToTop}
      aria-label="Scroll to top"
      title="Scroll to top"
      className="fixed right-5 sm:right-7 bottom-24 z-50 w-11 h-11 sm:w-12 sm:h-12 rounded-full bg-[#00AEF0] hover:bg-[#0F5065] text-white flex items-center justify-center shadow-2xl shadow-[#00AEF0]/40 border-2 border-white/20 hover:scale-110 active:scale-95 transition-all duration-200 animate-in fade-in zoom-in-75 cursor-pointer group"
    >
      <i className="fas fa-chevron-up text-base sm:text-lg group-hover:-translate-y-0.5 transition-transform"></i>
    </button>
  );
}
