// Neutral stand-ins shown while a cover/page is loading or missing. Inline
// SVG data URIs: no network request, no stock photography.

const svg = (body, w, h) =>
  `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">${body}</svg>`
  )}`;

// A blank comic page: panel grid on a muted background.
export const PAGE_PLACEHOLDER = svg(
  `<rect width="600" height="840" fill="#1b1e26"/>
   <g fill="none" stroke="#2f3442" stroke-width="6" rx="4">
     <rect x="40" y="40" width="520" height="250"/>
     <rect x="40" y="320" width="250" height="230"/>
     <rect x="310" y="320" width="250" height="230"/>
     <rect x="40" y="580" width="520" height="220"/>
   </g>
   <g fill="#2f3442"><circle cx="300" cy="165" r="34"/><rect x="262" y="205" width="76" height="40" rx="18"/></g>`,
  600,
  840
);

export const COVER_PLACEHOLDER = PAGE_PLACEHOLDER;

// Default avatar: a plain silhouette.
export const AVATAR_PLACEHOLDER = svg(
  `<rect width="100" height="100" fill="#262a33"/><circle cx="50" cy="38" r="18" fill="#5b6275"/><path d="M14 100c4-26 20-38 36-38s32 12 36 38z" fill="#5b6275"/>`,
  100,
  100
);

/** onError handler: swap in the placeholder once (no retry loop). */
export const useFallback = (fallback = PAGE_PLACEHOLDER) => (e) => {
  if (e.currentTarget.dataset.fallback) return;
  e.currentTarget.dataset.fallback = "1";
  e.currentTarget.src = fallback;
};
