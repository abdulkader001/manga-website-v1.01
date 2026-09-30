/**
 * Updates the browser tab favicon dynamically based on an image URL or emoji
 */
export function updateFavicon(iconUrlOrEmoji) {
  if (!iconUrlOrEmoji || typeof document === "undefined") return;

  let href = iconUrlOrEmoji;
  const isUrl =
    iconUrlOrEmoji.startsWith("http://") ||
    iconUrlOrEmoji.startsWith("https://") ||
    iconUrlOrEmoji.startsWith("data:") ||
    iconUrlOrEmoji.startsWith("/");

  if (!isUrl) {
    // Generate an SVG data URI with the emoji
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">${iconUrlOrEmoji}</text></svg>`;
    href = `data:image/svg+xml,${encodeURIComponent(svg)}`;
  }

  let link = document.querySelector("link[rel*='icon']");
  if (!link) {
    link = document.createElement("link");
    link.rel = "shortcut icon";
    document.head.appendChild(link);
  }
  link.href = href;

  const appleLink = document.querySelector("link[rel='apple-touch-icon']");
  if (appleLink) {
    appleLink.href = href;
  }
}
