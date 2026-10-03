import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import AntiTamperGuard, { isDevtoolsShortcut } from "./AntiTamperGuard";

describe("AntiTamperGuard", () => {
  it("blocks the developer-tool shortcuts on every platform", () => {
    expect(isDevtoolsShortcut({ key: "F12", code: "F12" })).toBe("inspect");
    expect(isDevtoolsShortcut({ ctrlKey: true, shiftKey: true, code: "KeyI" })).toBe("inspect");
    // Mac: Cmd+Option+I used to slip through.
    expect(isDevtoolsShortcut({ metaKey: true, altKey: true, code: "KeyI", key: "ˆ" })).toBe("inspect");
    expect(isDevtoolsShortcut({ ctrlKey: true, shiftKey: true, code: "KeyK" })).toBe("inspect");
    expect(isDevtoolsShortcut({ ctrlKey: true, code: "KeyU" })).toBe("source");
    expect(isDevtoolsShortcut({ metaKey: true, altKey: true, code: "KeyU" })).toBe("source");
  });

  it("leaves normal typing and AltGr characters alone", () => {
    expect(isDevtoolsShortcut({ ctrlKey: true, code: "KeyC" })).toBe(null); // copy
    expect(isDevtoolsShortcut({ ctrlKey: true, altKey: true, code: "KeyE" })).toBe(null); // AltGr+E = €
    expect(isDevtoolsShortcut({ code: "KeyI", key: "i" })).toBe(null);
  });

  it("gives text boxes its own menu instead of the browser's", () => {
    render(
      <AntiTamperGuard>
        <input aria-label="search" />
      </AntiTamperGuard>
    );
    const box = screen.getByLabelText("search");
    const allowed = fireEvent.contextMenu(box, { clientX: 10, clientY: 10 });
    expect(allowed).toBe(false); // browser menu (with "Inspect") prevented
    expect(screen.getByRole("menu")).toBeTruthy();
    expect(screen.getByText("Paste")).toBeTruthy();
  });

  it("blocks right-click elsewhere", () => {
    render(
      <AntiTamperGuard>
        <p>page</p>
      </AntiTamperGuard>
    );
    expect(fireEvent.contextMenu(screen.getByText("page"))).toBe(false);
    expect(screen.queryByRole("menu")).toBeNull();
  });
});
