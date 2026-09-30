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
