import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../services/api";
import CONFIG from "../config";

export const DEFAULT_LOGO = "📖";
export const DEFAULT_TAGLINE = "Read manga, manhwa and manhua online";
export const DEFAULT_HOMEPAGE_TITLE = "Recently Updated Manga Chapters";
export const DEFAULT_HOMEPAGE_SUBTITLE =
  "New chapters are immediately updated on our website as soon as they are translated.";

// Older versions saved branding edits in the visitor's own browser, so anyone
// (even a guest) could "change" the logo for themselves. Those copies are
// ignored now; clear them once.
const LEGACY_KEYS = [
  "mgeko_custom_brand",
  "mgeko_custom_logo",
  "mgeko_custom_tagline",
  "mgeko_header_title",
  "mgeko_header_subtitle",
];
try {
  LEGACY_KEYS.forEach((key) => localStorage.removeItem(key));
} catch {
  // storage blocked: nothing to clear
}

/**
 * The site's name, logo and tagline as the owner saved them on the server.
 * The same for every visitor; `save` needs the branding power (the server
 * checks it, with a fresh authenticator code).
 */
export default function useBranding() {
  const queryClient = useQueryClient();
  const { data } = useQuery({
    queryKey: ["branding"],
    queryFn: () => api.branding.get(),
    staleTime: 60_000,
    retry: 1,
  });
  const save = async (fields) => {
    const result = await api.branding.update(fields);
    await queryClient.invalidateQueries({ queryKey: ["branding"] });
    return result;
  };
  return {
    name: data?.name || CONFIG.BRAND_NAME,
    logo: data?.logo_url || data?.logo || DEFAULT_LOGO,
    tagline: data?.tagline || DEFAULT_TAGLINE,
    homepageTitle: data?.homepage_title || DEFAULT_HOMEPAGE_TITLE,
    homepageSubtitle: data?.homepage_subtitle ?? DEFAULT_HOMEPAGE_SUBTITLE,
    loaded: Boolean(data),
    save,
  };
}
