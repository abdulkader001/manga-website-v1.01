import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../../test/render";

const get = vi.fn();
const set = vi.fn();
vi.mock("../../services/api", () => ({
  default: { admin: { tabAccess: { get: (...a) => get(...a), set: (...a) => set(...a) } } },
}));

import TabAccessPanel from "./TabAccessPanel";

const TABS = [
  { key: "series", label: "Series Management", owner_power: false, owner_only: false },
  { key: "chapter-reports", label: "Chapter Reports", owner_power: false, owner_only: false },
  { key: "vault", label: "Secret Vault", owner_power: true, owner_only: false },
];
const overview = (people) => ({ tabs: TABS, people });
const sub = (extra = {}) => ({ user_id: 7, name: "Mod Moe", role: "sub_admin", tabs: null, suspended: false, authenticator: true, ...extra });

describe("Tab access (owner only)", () => {
  beforeEach(() => {
    get.mockReset();
    set.mockReset();
  });

  it("gives a report moderator just the reports tab", async () => {
    get.mockResolvedValue(overview([sub()]));
    set.mockResolvedValue(overview([sub({ tabs: ["chapter-reports"] })]));
    const user = userEvent.setup();
    renderAt(<TabAccessPanel flash={() => {}} />);
    await user.click(await screen.findByLabelText(/Follow their permissions/));
    await user.click(screen.getByLabelText("Mod Moe: Chapter Reports"));
    await user.click(screen.getByRole("button", { name: "Save tabs" }));
    await waitFor(() => expect(set).toHaveBeenCalledWith(7, { tabs: ["chapter-reports"], suspended: false }));
  });

  it("never offers a sub-admin the site-owner tabs", async () => {
    get.mockResolvedValue(overview([sub({ tabs: [] })]));
    renderAt(<TabAccessPanel flash={() => {}} />);
    expect(await screen.findByLabelText("Mod Moe: Series Management")).toBeInTheDocument();
    expect(screen.queryByLabelText("Mod Moe: Secret Vault")).not.toBeInTheDocument();
  });

  it("switches all of an Admin's powers off, keeping the seat", async () => {
    const admin = { user_id: 3, name: "Ada", role: "admin", tabs: null, suspended: false, authenticator: true };
    get.mockResolvedValue(overview([admin]));
    set.mockResolvedValue(overview([{ ...admin, suspended: true }]));
    const user = userEvent.setup();
    renderAt(<TabAccessPanel flash={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "Switch all powers off" }));
    await waitFor(() => expect(set).toHaveBeenCalledWith(3, { tabs: null, suspended: true }));
    expect(await screen.findByText("all powers off")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Switch powers back on" })).toBeInTheDocument();
  });

  it("shows the server's refusal", async () => {
    get.mockResolvedValue(overview([sub()]));
    set.mockRejectedValue(new Error("Unknown tab: nope"));
    const user = userEvent.setup();
    renderAt(<TabAccessPanel flash={() => {}} />);
    await user.click(await screen.findByRole("button", { name: "Save tabs" }));
    expect(await screen.findByText("Unknown tab: nope")).toBeInTheDocument();
  });
});
