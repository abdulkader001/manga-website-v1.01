import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { renderAt } from "../test/render";

const api = vi.hoisted(() => ({
  manga: { chapter: vi.fn(), chapters: vi.fn() },
  reports: { getChapterReports: vi.fn() },
  bookmarks: { list: vi.fn() },
}));
vi.mock("../services/api", () => ({ default: api, apiFetch: vi.fn() }));
vi.mock("../hooks/useAuth", () => ({
  default: () => ({ isAdmin: false, isSecondaryAdmin: false, user: null }),
}));
// The reader's neighbours have their own data needs; they are not under test.
vi.mock("./ReaderOverlay", () => ({ default: () => null }));
vi.mock("./OverlayScaleControl", () => ({ default: () => null }));
vi.mock("./GlobalAds", () => ({ default: () => null }));
vi.mock("./AdPlacement", () => ({ default: () => null }));
vi.mock("./CommentSection", () => ({ default: () => null }));

import ChapterViewer from "./ChapterViewer";

const ROUTE = "/manga/:mangaId/chapter/:chapterId";
const open = () => renderAt(<ChapterViewer />, { path: "/manga/7/chapter/21", route: ROUTE });

describe("Reader (ChapterViewer)", () => {
  beforeEach(() => {
    Object.values(api).forEach((group) => Object.values(group).forEach((fn) => fn.mockReset()));
    api.manga.chapters.mockResolvedValue([]);
    api.reports.getChapterReports.mockResolvedValue({});
    localStorage.clear();
  });

  it("shows every page image in order", async () => {
    api.manga.chapter.mockResolvedValue({
      id: 21,
      chapter_number: 3,
      pages: ["https://cdn.test/p1.webp", { image_url: "https://cdn.test/p2.webp" }, ["https://cdn.test/p3.webp"]],
    });
    open();
    const first = await screen.findByAltText("Chapter Page 1");
    expect(first).toHaveAttribute("src", "https://cdn.test/p1.webp");
    expect(screen.getByAltText("Chapter Page 2")).toHaveAttribute("src", "https://cdn.test/p2.webp");
    expect(screen.getByAltText("Chapter Page 3")).toHaveAttribute("src", "https://cdn.test/p3.webp");
    expect(api.manga.chapter).toHaveBeenCalledWith("7", "21");
  });

  it("remembers the chapter as read on this device", async () => {
    api.manga.chapter.mockResolvedValue({ id: 21, chapter_number: 3, pages: ["https://cdn.test/p1.webp"] });
    open();
    await screen.findByAltText("Chapter Page 1");
    const lib = JSON.parse(localStorage.getItem("mw_library_v1"));
    // Only the chapter that was opened is marked; chapters 1 and 2 are not.
    expect(Object.keys(lib.read["7"])).toEqual(["21"]);
    expect(lib.last["7"].chapterId).toBe(21);
  });

  it("shows the series title the API sends", async () => {
    api.manga.chapter.mockResolvedValue({
      id: 21,
      chapter_number: 3,
      manga_title: "Solo Leveling",
      pages: ["https://cdn.test/p1.webp"],
    });
    open();
    expect(await screen.findByText("Solo Leveling")).toBeInTheDocument();
    expect(screen.queryByText("Manga #7")).not.toBeInTheDocument();
  });

  it("says so when a chapter has no pages", async () => {
    api.manga.chapter.mockResolvedValue({ id: 21, chapter_number: 3, pages: [] });
    open();
    expect(await screen.findByText(/No images found in this chapter/i)).toBeInTheDocument();
  });

  it("shows an error when the chapter cannot be loaded", async () => {
    api.manga.chapter.mockImplementation(async () => {
      throw new Error("Chapter was taken down");
    });
    open();
    expect(await screen.findByText("Chapter Load Error")).toBeInTheDocument();
    expect(screen.getByText("Chapter was taken down")).toBeInTheDocument();
  });
});
