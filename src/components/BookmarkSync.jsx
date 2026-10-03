import { useEffect } from "react";
import api from "../services/api";
import useAuth from "../hooks/useAuth";
import {
  bookmarkIds,
  clearPendingBookmarks,
  onBookmarkChange,
  pendingBookmarkChanges,
  setBookmarks,
} from "../utils/library";

// The browser that first uploaded its bookmarks for an account. Its whole
// list is sent once; later sign-ins send only the changes made meanwhile.
const SYNCED_KEY = "mw_bookmarks_synced_user";

function syncedUser() {
  try {
    return localStorage.getItem(SYNCED_KEY);
  } catch {
    return null;
  }
}

/**
 * Keeps a signed-in reader's bookmarks (series ids only) on the server, so
 * new-chapter alerts reach them and the list follows them to other devices.
 * Guests are never synced. Renders nothing.
 */
export default function BookmarkSync() {
  const { user } = useAuth();
  const userId = user?.id;

  useEffect(() => {
    if (!userId) return undefined;
    let alive = true;

    // From now on every change goes straight to the server.
    const stop = onBookmarkChange((id, on) => {
      const call = on ? api.bookmarks.add(Number(id)) : api.bookmarks.remove(Number(id));
      call.catch(() => {});
    });

    (async () => {
      const pending = pendingBookmarkChanges();
      const firstTime = syncedUser() === null;
      const adds = new Set(Object.keys(pending).filter((id) => pending[id] === "add"));
      if (firstTime) bookmarkIds().forEach((id) => adds.add(id));
      const removes = Object.keys(pending).filter((id) => pending[id] === "remove");

      try {
        if (adds.size) {
          await api.bookmarks.importBackup({
            bookmarks: [...adds].map((id) => ({ manga_id: Number(id) })),
          });
        }
        for (const id of removes) {
          await api.bookmarks.remove(Number(id)).catch((err) => {
            if (err?.status !== 404) throw err; // already gone is fine
          });
        }
      } catch {
        // Not uploaded: keep this browser's list as it is and try next time.
        return;
      }
      clearPendingBookmarks();
      try {
        localStorage.setItem(SYNCED_KEY, String(userId));
      } catch {
        // storage blocked: the full list is sent again next time (harmless)
      }

      const rows = await api.bookmarks.list();
      if (alive && Array.isArray(rows)) setBookmarks(rows.map((row) => row.manga_id));
    })().catch(() => {});

    return () => {
      alive = false;
      stop();
    };
  }, [userId]);

  return null;
}
