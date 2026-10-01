import { useQuery } from "@tanstack/react-query";
import api from "../services/api";
import useAuth from "./useAuth";
import useReaderSettings from "./useReaderSettings";

// Readable chapter titles ("Chapter 522: The Reunion") in the reader's
// language. The server strips source noise like "522 원준 522화 2024-11-07"
// and translates real subtitles once, caching them per chapter.
export default function useChapterTitles(mangaId) {
  const { user } = useAuth();
  const { settings } = useReaderSettings({ enabled: Boolean(user) });
  const lang = (user && settings.target_language) || "en";

  const { data } = useQuery({
    queryKey: ["chapterTitles", String(mangaId), lang],
    queryFn: () => api.manga.chapterTitles(mangaId, lang),
    enabled: Boolean(mangaId),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const titles = data?.titles || {};

  /** Display label for a chapter object (or a {id, chapter_number} pair). */
  return (chapter) => {
    if (!chapter) return "";
    const known = titles[String(chapter.id)];
    if (known?.title) return known.title;
    if (chapter.title) return chapter.title;
    return chapter.chapter_number != null ? `Chapter ${chapter.chapter_number}` : `Chapter #${chapter.id}`;
  };
}
