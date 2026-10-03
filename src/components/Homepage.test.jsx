import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../test/render";

const browse = vi.fn();
vi.mock("../services/api", () => ({
  default: { manga: { browse: (...a) => browse(...a) } },
  apiFetch: () => Promise.resolve({}),
}));
vi.mock("../hooks/useAuth", () => ({ default: () => ({ user: null, isAdmin: false, isSecondaryAdmin: false }) }));
vi.mock("../hooks/useStaffPermissions", () => ({ default: () => ({ can: () => false }) }));
vi.mock("../hooks/useBranding", () => ({ default: () => ({}) }));
vi.mock("./GlobalAds", () => ({ default: () => null }));
vi.mock("./AdPlacement", () => ({ default: () => null }));

import Homepage from "./Homepage";

const sortsRequested = () => browse.mock.calls.map(([params]) => params.sort);

describe("Homepage sliders (plan.md P1-7)", () => {
  beforeEach(() => {
    browse.mockReset();
    browse.mockResolvedValue({ items: [], total: 0 });
  });

  it("asks the server for Most viewed and New over the whole catalogue", async () => {
    renderAt(<Homepage />);
    await waitFor(() => expect(sortsRequested()).toEqual(expect.arrayContaining(["latest", "views_today", "new"])));
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Week" }));
    await waitFor(() => expect(sortsRequested()).toContain("views_week"));
    await user.click(screen.getByRole("button", { name: "Month" }));
    await waitFor(() => expect(sortsRequested()).toContain("views_month"));
  });
});
