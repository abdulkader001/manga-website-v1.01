import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../../test/render";

const api = vi.hoisted(() => ({
  manga: { browse: vi.fn() },
  admin: { series: { add: vi.fn() } },
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
});
