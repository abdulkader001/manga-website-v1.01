import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../../test/render";

const api = vi.hoisted(() => ({
  manga: { browse: vi.fn() },
  admin: { series: { add: vi.fn(), rescrape: vi.fn(), remove: vi.fn(), batch: vi.fn() } },
  scraper: { listParsers: vi.fn(), startPreview: vi.fn(), getTask: vi.fn() },
}));
vi.mock("../../services/api", () => ({
  default: api,
  apiFetch: vi.fn(async () => ({ json: async () => ({}) })),
}));

import SeriesManagement from "./SeriesManagement";

async function openImportForm(user) {
  await user.click(await screen.findByRole("button", { name: /Import & Scrape Manga/i }));
  return {
    base: await screen.findByPlaceholderText(/baozimh\.com/i),
    series: screen.getByPlaceholderText(/asuracomic\.net\/series/i),
  };
}

describe("Admin series import", () => {
  beforeEach(() => {
    api.manga.browse.mockReset().mockResolvedValue({ items: [] });
    api.admin.series.add.mockReset();
    api.scraper.listParsers.mockReset().mockResolvedValue({ items: [] });
  });

  it("sends the source and series URLs to the import endpoint", async () => {
    api.admin.series.add.mockResolvedValue({ message: "Imported 12 chapters" });
    const user = userEvent.setup();
    renderAt(<SeriesManagement />);
    const { base, series } = await openImportForm(user);
    await user.type(base, "https://source.example");
    await user.type(series, "https://source.example/series/solo");
    await user.click(screen.getByRole("button", { name: /Start Auto-Scrape/i }));

    await waitFor(() => expect(api.admin.series.add).toHaveBeenCalledTimes(1));
    expect(api.admin.series.add).toHaveBeenCalledWith(
      expect.objectContaining({
        base_url: "https://source.example",
        url: "https://source.example/series/solo",
        source_url: "https://source.example/series/solo",
      })
    );
    expect(await screen.findByText(/Imported 12 chapters/)).toBeInTheDocument();
  });

  it("refuses a URL that points at an internal address", async () => {
    const user = userEvent.setup();
    renderAt(<SeriesManagement />);
    const { base, series } = await openImportForm(user);
    await user.type(base, "http://127.0.0.1:8000");
    await user.type(series, "http://127.0.0.1:8000/series/x");
    await user.click(screen.getByRole("button", { name: /Start Auto-Scrape/i }));

    expect(await screen.findByText(/Malicious or unsafe URL blocked/i)).toBeInTheDocument();
    expect(api.admin.series.add).not.toHaveBeenCalled();
  });

  it("shows the server's reason when the import fails", async () => {
    api.admin.series.add.mockImplementation(async () => {
      throw new Error("Source site returned 0 chapters");
    });
    const user = userEvent.setup();
    renderAt(<SeriesManagement />);
    const { base, series } = await openImportForm(user);
    await user.type(base, "https://source.example");
    await user.type(series, "https://source.example/series/solo");
    await user.click(screen.getByRole("button", { name: /Start Auto-Scrape/i }));

    expect(await screen.findByText(/Failed to import series: Source site returned 0 chapters/)).toBeInTheDocument();
  });

  it("re-scrapes a series after its name is typed back (the server requires it)", async () => {
    api.manga.browse.mockResolvedValue({ items: [{ id: 7, title: "Solo Story", chapters_count: 3 }] });
    api.admin.series.rescrape.mockReset().mockResolvedValue({ ok: true });
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("Solo Story");
    const user = userEvent.setup();
    renderAt(<SeriesManagement />);
    await user.click(await screen.findByTitle("Rescrape & sync now"));
    expect(prompt).toHaveBeenCalled();
    expect(api.admin.series.rescrape).toHaveBeenCalledWith(7, "Solo Story");
    expect(await screen.findByText(/Re-scrape of "Solo Story" started/)).toBeInTheDocument();
    prompt.mockRestore();
  });

  it("does not re-scrape when the typed name is wrong, and asks before deleting", async () => {
    api.manga.browse.mockResolvedValue({ items: [{ id: 7, title: "Solo Story", chapters_count: 3 }] });
    api.admin.series.rescrape.mockReset();
    api.admin.series.remove.mockReset().mockResolvedValue({ ok: true });
    const prompt = vi.spyOn(window, "prompt").mockReturnValue("Solo");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    renderAt(<SeriesManagement />);
    await user.click(await screen.findByTitle("Rescrape & sync now"));
    expect(api.admin.series.rescrape).not.toHaveBeenCalled();
    expect(await screen.findByText(/doesn't match the series name/)).toBeInTheDocument();
    await user.click(screen.getByTitle("Delete"));
    expect(api.admin.series.remove).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    await user.click(screen.getByTitle("Delete"));
    expect(api.admin.series.remove).toHaveBeenCalledWith(7);
    prompt.mockRestore();
    confirm.mockRestore();
  });

  it("imports many series at once from pasted text and shows each result", async () => {
    api.admin.series.batch.mockReset().mockResolvedValue({
      queued: 1,
      failed: 1,
      results: [
        { url: "https://a.example/manga/one", ok: true },
        { url: "https://b.example/comic/2", ok: false, error: "This website is not approved yet" },
      ],
    });
    const user = userEvent.setup();
    // After setup(): user-event installs its own clipboard on navigator.
    const readText = vi.fn(async () => "Look: https://a.example/manga/one, and https://b.example/comic/2.");
    Object.defineProperty(navigator, "clipboard", { value: { readText }, configurable: true });
    renderAt(<SeriesManagement />);
    await user.click(await screen.findByRole("button", { name: /Import many at once/i }));
    const panel = await screen.findByRole("form", { name: /Import many series at once/i });
    await user.click(within(panel).getByRole("button", { name: /Paste/i }));
    expect(await within(panel).findByText(/2 addresses found/)).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: /Import all/i }));

    await waitFor(() =>
      expect(api.admin.series.batch).toHaveBeenCalledWith(["https://a.example/manga/one", "https://b.example/comic/2"])
    );
    expect(await within(panel).findByText(/1 queued, 1 not added/)).toBeInTheDocument();
    expect(within(panel).getByText(/not approved yet/)).toBeInTheDocument();
  });

  it("pastes the first link into a single address box", async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      value: { readText: vi.fn(async () => "Solo https://source.example/series/solo") },
      configurable: true,
    });
    renderAt(<SeriesManagement />);
    const { series } = await openImportForm(user);
    const pasteButtons = screen.getAllByRole("button", { name: /^Paste$/i });
    await user.click(pasteButtons[pasteButtons.length - 1]);
    await waitFor(() => expect(series).toHaveValue("https://source.example/series/solo"));
  });
});
