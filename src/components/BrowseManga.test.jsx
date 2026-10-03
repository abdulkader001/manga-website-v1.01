import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../test/render";

const browse = vi.fn();
vi.mock("../services/api", () => ({ default: { manga: { browse: (...a) => browse(...a) } } }));
vi.mock("../hooks/useAuth", () => ({ default: () => ({ user: null }) }));
vi.mock("./GlobalAds", () => ({ default: () => null }));
vi.mock("./AdPlacement", () => ({ default: () => null }));

import BrowseManga from "./BrowseManga";

const page = (items, total) => ({ items, total, page: 1, per_page: 48, genres: [], cache_hit: true });
const series = (id, extra = {}) => ({ id, title: `Series ${id}`, genres: [], chapters_count: 3, ...extra });
const lastCall = () => browse.mock.calls[browse.mock.calls.length - 1][0];

describe("Browse (plan.md P1-3, P1-4)", () => {
  beforeEach(() => {
    browse.mockReset();
  });

  it("sends the address's search, sort and genre to the server", async () => {
    browse.mockResolvedValue(page([series(77)], 1));
    renderAt(<BrowseManga />, { path: "/browse?search=Series%20077&sort=new&genre=Horror" });
    await screen.findByText("Series 77");
    expect(lastCall()).toMatchObject({ search: "Series 077", sort: "new", include: "Horror" });
    // "Hide NSFW" is on by default and goes to the server too.
    expect(lastCall().exclude).toContain("Ecchi");
  });

  it("shows the server's total, pages from it and has no fixed badge", async () => {
    browse.mockResolvedValue(page([series(1), series(2)], 121));
    renderAt(<BrowseManga />, { path: "/browse" });
    expect(await screen.findByText("121 Comics")).toBeInTheDocument();
    expect(screen.getByText("1 / 3")).toBeInTheDocument();
    expect(screen.queryByText("Trending")).not.toBeInTheDocument();
    expect(screen.queryByText(/7004/)).not.toBeInTheDocument();
  });

  it("disables Next on the last page", async () => {
    browse.mockResolvedValue(page([series(1)], 1));
    renderAt(<BrowseManga />, { path: "/browse" });
    await screen.findByText("Series 1");
    expect(screen.getByRole("button", { name: "Next »" })).toBeDisabled();
  });

  it("goes back to page 1 when a filter changes", async () => {
    browse.mockResolvedValue(page([series(1)], 200));
    const user = userEvent.setup();
    renderAt(<BrowseManga />, { path: "/browse?page=3" });
    await screen.findByText("Series 1");
    expect(lastCall().page).toBe(3);
    await user.click(screen.getAllByRole("button", { name: "Action" })[0]);
    await waitFor(() => expect(lastCall()).toMatchObject({ page: 1, include: "Action" }));
  });

  it("does not filter the server's page again in the browser", async () => {
    browse.mockResolvedValue(page([series(1, { genres: ["Romance"], chapters_count: 2 })], 1));
    renderAt(<BrowseManga />, { path: "/browse?genre=Horror" });
    expect(await screen.findByText("Series 1")).toBeInTheDocument();
  });
});
