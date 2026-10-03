// Pull web addresses out of pasted text (a copied page title + link, a list
// from a chat, one link per line...).

const LINK_RE = /https?:\/\/[^\s"'<>]+/gi;
// Punctuation that ends a sentence rather than the address.
const TRAILING_RE = /[),.;:!?\]]+$/;

export function extractLinks(text) {
  const seen = new Set();
  const links = [];
  for (const match of String(text || "").match(LINK_RE) || []) {
    const link = match.replace(TRAILING_RE, "");
    if (link && !seen.has(link)) {
      seen.add(link);
      links.push(link);
    }
  }
  return links;
}

// The first address in the text, or the trimmed text itself when it holds
// none (so a bare "example.com/manga/x" still lands in the box).
export function firstLink(text) {
  const [link] = extractLinks(text);
  return link || String(text || "").trim();
}
