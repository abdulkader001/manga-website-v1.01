// Right-click on a manga card opens that manga in a new tab; Shift (or the
// Windows / Cmd key) + right-click opens it in a new window. Nothing else
// changes: everywhere else the anti-tamper guard still blocks the menu.

const MANGA_PAGE = /^\/manga\/\d+\/?$/;

export function mangaLinkFrom(target) {
  const link = target && typeof target.closest === "function" ? target.closest("a[href]") : null;
  if (!link) return null;
  let url;
  try {
    url = new URL(link.getAttribute("href"), window.location.origin);
  } catch {
    return null;
  }
  // Only this site's own manga pages, never an outside or script link.
  if (url.origin !== window.location.origin || !MANGA_PAGE.test(url.pathname)) return null;
  return url.href;
}

export function handleMangaContextMenu(event) {
  const href = mangaLinkFrom(event.target);
  if (!href) return false;
  event.preventDefault();
  const newWindow = event.shiftKey || event.metaKey;
  const features = newWindow
    ? `noopener,noreferrer,popup,width=${Math.round(window.outerWidth * 0.9) || 1200},height=${Math.round(window.outerHeight * 0.9) || 900}`
    : "noopener,noreferrer";
  window.open(href, "_blank", features);
  return true;
}
