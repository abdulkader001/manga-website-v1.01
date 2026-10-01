// Overlay lettering fonts (all SIL Open Font License, self-hosted through
// @fontsource so nothing is fetched from a third party). Importing the CSS
// only declares @font-face rules; a font file downloads the first time a
// box actually uses that family.
import "@fontsource/inter/400.css";
import "@fontsource/inter/700.css";
import "@fontsource/comic-neue/700.css";
import "@fontsource/shantell-sans/600.css";
import "@fontsource/bangers/400.css";
import "@fontsource/luckiest-guy/400.css";
import "@fontsource/mali/600.css";
import "@fontsource/patrick-hand/400.css";
import "@fontsource/kalam/700.css";
import "@fontsource/permanent-marker/400.css";
import "@fontsource/pinyon-script/400.css";

// Mirrors services/overlay_fonts.py. Used when the server list has not
// loaded yet, and as the source of each id's font weight.
export const OVERLAY_FONTS = [
  { id: "standard_sans", label: "Standard", css_family: "'Inter', 'Helvetica Neue', Arial, sans-serif", weight: 700 },
  { id: "anime_ace", label: "Comic Lettering", css_family: "'Comic Neue', 'Comic Sans MS', sans-serif", weight: 700 },
  { id: "wild_words", label: "Speech Bubble", css_family: "'Shantell Sans', 'Comic Sans MS', sans-serif", weight: 600 },
  { id: "bangers", label: "Action (Bangers)", css_family: "'Bangers', Impact, sans-serif", weight: 400, spacing: "0.03em" },
  { id: "luckiest_guy", label: "Shout (Luckiest Guy)", css_family: "'Luckiest Guy', Impact, sans-serif", weight: 400 },
  { id: "mali", label: "Soft Manga (Mali)", css_family: "'Mali', 'Comic Sans MS', sans-serif", weight: 600 },
  { id: "casual_handwriting", label: "Handwriting", css_family: "'Patrick Hand', 'Segoe Print', cursive", weight: 400 },
  { id: "kalam", label: "Pen (Kalam)", css_family: "'Kalam', 'Segoe Print', cursive", weight: 700 },
  { id: "permanent_marker", label: "Marker", css_family: "'Permanent Marker', 'Segoe Print', cursive", weight: 400 },
  { id: "manga_calligraphy", label: "Calligraphy", css_family: "'Pinyon Script', 'Brush Script MT', cursive", weight: 400 },
];

export function fontStyleFor(fontId) {
  const font = OVERLAY_FONTS.find((f) => f.id === fontId) || OVERLAY_FONTS[0];
  return {
    fontFamily: font.css_family,
    fontWeight: font.weight,
    letterSpacing: font.spacing || "normal",
  };
}
