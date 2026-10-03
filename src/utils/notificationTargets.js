// Machine target_type -> where a notification should navigate on click
// (SRS 1I.2.2: "Each notification is clickable and navigates to the thing
// it is about"). Shared by the bell dropdown and the full notifications
// page so the two never drift.
export function targetPathFor(note) {
  if (note?.link) return note.link;
  const targetType = note?.target_type;
  const targetId = note?.target_id;
  if (!targetType) return note?.link || null;

  switch (targetType) {
    case "series":
      return `/manga/${targetId}`;
    case "chapter": {
      const mangaId = note?.data?.manga_id;
      if (mangaId && targetId) return `/reader/${mangaId}/${targetId}`;
      if (mangaId) return `/manga/${mangaId}`;
      return null;
    }
    case "announcement":
    case "broadcast":
      return "/";
    case "user":
      return "/settings";
    default:
      return note?.link || null;
  }
}

// The server's machine types (backend notification_service.TYPE_CATEGORY).
// The page used to look for categories "chapter_issue" / "chapter_release"
// that the server never sends, so the Chapter Alerts tab was always empty and
// new-chapter alerts had no badge.
const CHAPTER_PROBLEM_TYPES = new Set([
  "chapter.reported",
  "chapter.fix_failed",
  "chapter.repeatedly_broken",
]);

export function isNewChapterAlert(note) {
  return note?.type === "chapter.new";
}

export function isChapterFixed(note) {
  return note?.type === "chapter.fix_completed";
}

export function isChapterProblem(note) {
  return CHAPTER_PROBLEM_TYPES.has(note?.type);
}

// Everything the "Chapter Alerts & Issues" tab shows.
export function isChapterAlert(note) {
  return isNewChapterAlert(note) || isChapterFixed(note) || isChapterProblem(note);
}

export function isBroadcast(note) {
  return ["announcement", "popup", "system"].includes(note?.type);
}

export function isUnread(note) {
  return !note?.read && !note?.is_read;
}
