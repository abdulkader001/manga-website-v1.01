import { useEffect } from "react";
import api from "../services/api";
import useAuth from "../hooks/useAuth";
import {
  onHistoryChange,
  queueAllReads,
  resetHistory,
  restorePendingHistory,
  setReadFromAccount,
  takePendingHistory,
} from "../utils/library";

// Which account this browser's reading was last matched with. A browser that
// has never been signed in sends everything it has (a guest becoming a reader);
// a different account on the same browser starts from its own list instead.
const SYNCED_KEY = "mw_history_synced_user";
const CHUNK = 2000; // the server takes at most this many chapters per request

function syncedUser() {
  try {
    return localStorage.getItem(SYNCED_KEY);
  } catch {
    return null;
  }
}

/** Send the queued changes in pieces; the last answer is the account's list. */
async function sendPending() {
  const taken = takePendingHistory();
  const chapters = Object.entries(taken.reads);
  const clearManga = Object.keys(taken.clear.manga).map(Number);
  try {
    let entries = [];
    let start = 0;
    do {
      const piece = chapters.slice(start, start + CHUNK);
      start += CHUNK;
      const first = start === CHUNK;
      const res = await api.history.sync({
        entries: piece.map(([chapterId, at]) => ({ chapter_id: Number(chapterId), read_at: at })),
        clear_all: first && taken.clear.all,
        clear_manga: first ? clearManga : [],
        return_entries: start >= chapters.length,
      });
      entries = res?.entries || [];
    } while (start < chapters.length);
    return entries;
  } catch (err) {
    restorePendingHistory(taken); // keep it for the next time
    throw err;
  }
}

/**
 * Keeps a signed-in reader's read chapters on their account, so the dimmed
 * chapters and "where I stopped" follow them to another phone or computer.
 * Only chapter ids and when they were opened are sent. Guests are never
 * synced. Renders nothing.
 */
export default function HistorySync() {
  const { user } = useAuth();
  const userId = user?.id;

  useEffect(() => {
    if (!userId) return undefined;
    let alive = true;

    const queueFailed = (change) => restorePendingHistory(change);
    // From now on every change goes straight to the account.
    const stop = onHistoryChange((event) => {
      const failed = () => {
        if (event.type === "read") {
          queueFailed({ reads: { [event.chapterId]: event.at }, clear: { all: false, manga: {} } });
        } else if (event.type === "clear") {
          queueFailed({ reads: {}, clear: { all: false, manga: { [event.mangaId]: true } } });
        } else if (event.type === "clearAll") {
          queueFailed({ reads: {}, clear: { all: true, manga: {} } });
        }
      };
      if (event.type === "read") {
        api.history.read(event.chapterId, event.at).catch(failed);
      } else if (event.type === "clear") {
        api.history.sync({ clear_manga: [event.mangaId], return_entries: false }).catch(failed);
      } else if (event.type === "clearAll") {
        api.history.sync({ clear_all: true, return_entries: false }).catch(failed);
      } else if (event.type === "flush") {
        sendPending().catch(() => {});
      }
    });

    (async () => {
      const startedAt = new Date().toISOString();
      const previous = syncedUser();
      if (previous === null) queueAllReads();
      else if (previous !== String(userId)) resetHistory();

      let entries;
      try {
        entries = await sendPending();
      } catch {
        return; // not sent: this device keeps what it has and tries next time
      }
      try {
        localStorage.setItem(SYNCED_KEY, String(userId));
      } catch {
        // storage blocked: everything is sent again next time (harmless)
      }
      if (alive) setReadFromAccount(entries, startedAt);
    })().catch(() => {});

    return () => {
      alive = false;
      stop();
    };
  }, [userId]);

  return null;
}
