import { describe, it, expect, vi, beforeEach } from "vitest";
import { handleMangaContextMenu } from "./mangaLinkMenu";

function rightClick(el, mods = {}) {
  const event = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, button: 2, ...mods });
  let handled;
  document.addEventListener("contextmenu", (e) => (handled = handleMangaContextMenu(e)), { once: true });
  el.dispatchEvent(event);
  return { handled, prevented: event.defaultPrevented };
}

describe("right-click on manga cards", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <a id="card" href="/manga/42"><img id="cover" /></a>
      <a id="reader" href="/reader/42/7">ch</a>
      <a id="outside" href="https://evil.example/manga/1">x</a>
      <p id="text">hi</p>`;
    window.open = vi.fn();
  });

  it("opens the manga in a new tab, even from the cover image", () => {
    const r = rightClick(document.getElementById("cover"));
    expect(r).toEqual({ handled: true, prevented: true });
    expect(window.open).toHaveBeenCalledWith(`${window.location.origin}/manga/42`, "_blank", "noopener,noreferrer");
  });

  it("opens a new window with Shift or the Windows/Cmd key", () => {
    rightClick(document.getElementById("card"), { shiftKey: true });
    rightClick(document.getElementById("card"), { metaKey: true });
    for (const call of window.open.mock.calls) expect(call[2]).toMatch(/popup/);
  });

  it("leaves everything else alone", () => {
    for (const id of ["reader", "outside", "text"]) {
      expect(rightClick(document.getElementById(id))).toEqual({ handled: false, prevented: false });
    }
    expect(window.open).not.toHaveBeenCalled();
  });
});
