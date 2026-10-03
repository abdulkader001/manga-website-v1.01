import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { renderAt } from "../test/render";

const detail = vi.fn();
const chapters = vi.fn();
vi.mock("../services/api", () => ({
  default: {
    manga: { detail: (...a) => detail(...a), chapters: (...a) => chapters(...a), rate: vi.fn() },
  },
}));
vi.mock("../hooks/useAuth", () => ({ default: () => ({ user: null }) }));
vi.mock("../hooks/useChapterTitles", () => ({
  default: () => (ch) => (ch ? `Chapter ${ch.chapter_number}` : ""),
}));
vi.mock("./CommentSection", () => ({ default: () => null }));
vi.mock("./FunctionGate", () => ({ default: () => null }));

import MangaDetail, { chapterSortKey } from "./MangaDetail";

const list = [
  { id: 11, chapter_number: 0, title: "Prologue" },
  { id: 12, chapter_number: 1, title: "One" },
  { id: 13, chapter_number: 2, title: "Two" },
];

describe("Series page with a chapter 0 (plan.md P1-8)", () => {
  beforeEach(() => {
    detail.mockReset();
    chapters.mockReset();
    chapters.mockResolvedValue(list);
  });

  it("opens chapter 2 as the latest and chapter 0 as the first", async () => {
    detail.mockResolvedValue({ id: 5, title: "Zero", genres: [], type: "manga", status: "ongoing" });
    renderAt(<MangaDetail />, { path: "/manga/5", route: "/manga/:mangaId" });
    const latest = await screen.findByText("Read Latest (Chapter 2)");
    expect(latest.closest("a")).toHaveAttribute("href", "/reader/5/13");
    expect(screen.getByText("First Chapter").closest("a")).toHaveAttribute("href", "/reader/5/11");
  });

  it("prefers the chapter ids the server sends", async () => {
    detail.mockResolvedValue({
      id: 5, title: "Zero", genres: [], type: "manga", status: "ongoing",
      first_chapter_id: 12, latest_chapter_id: 12,
    });
    renderAt(<MangaDetail />, { path: "/manga/5", route: "/manga/:mangaId" });
    const latest = await screen.findByText("Read Latest (Chapter 1)");
    expect(latest.closest("a")).toHaveAttribute("href", "/reader/5/12");
  });

  it("sorts chapter 0 first and chapters without a number last", () => {
    expect(chapterSortKey({ chapter_number: 0 })).toBe(0);
    expect(chapterSortKey({ chapter_number: "1.5" })).toBe(1.5);
    expect(chapterSortKey({ chapter_number: null })).toBe(Infinity);
  });
});
