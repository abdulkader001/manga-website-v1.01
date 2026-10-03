import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../test/render";

const footer = vi.hoisted(() => ({
  get: vi.fn(),
  update: vi.fn(),
  getSocialLinks: vi.fn(),
  saveSocialLinks: vi.fn(),
  addSocialLink: vi.fn(),
  updateSocialLink: vi.fn(),
  deleteSocialLink: vi.fn(),
}));
vi.mock("../services/api", () => ({ default: { footer } }));

import FooterEditor from "./FooterEditor";

const links = [
  { id: 1, platform: "discord", title: "Discord", url: "https://discord.gg/x", icon: "fab fa-discord", enabled: true },
  { id: 2, platform: "twitter", title: "Twitter", url: "https://x.com/y", icon: "fab fa-twitter", enabled: true },
];

describe("Footer editor shows what the server stored (plan.md P1-10)", () => {
  beforeEach(() => {
    Object.values(footer).forEach((fn) => fn.mockReset());
    footer.get.mockResolvedValue({ copyright: "c", disclaimer: "d", social_links: links });
  });

  it("keeps a link the server refused to delete, and says so", async () => {
    footer.deleteSocialLink.mockImplementation(async () => {
      throw new Error("Not allowed");
    });
    const user = userEvent.setup();
    renderAt(<FooterEditor />);
    await screen.findByText("Discord");
    await user.click(screen.getAllByTitle("Delete this social link")[0]);
    await user.click(screen.getByRole("button", { name: /Delete Link/ }));
    expect(await screen.findByText(/The link was not deleted: Not allowed/)).toBeInTheDocument();
    expect(screen.getByText("Discord")).toBeInTheDocument();
    expect(screen.queryByText(/removed from footer/)).not.toBeInTheDocument();
  });

  it("leaves the order as it was when the server refuses a move", async () => {
    footer.saveSocialLinks.mockImplementation(async () => {
      throw new Error("offline");
    });
    const user = userEvent.setup();
    renderAt(<FooterEditor />);
    await screen.findByText("Discord");
    await user.click(screen.getAllByTitle("Move down")[0]);
    expect(await screen.findByText(/The new order was not saved: offline/)).toBeInTheDocument();
    const titles = screen.getAllByText(/^(Discord|Twitter)$/).map((n) => n.textContent);
    expect(titles).toEqual(["Discord", "Twitter"]);
  });

  it("shows the server's list after a successful change", async () => {
    footer.saveSocialLinks.mockResolvedValue({ links: [links[1], links[0]] });
    const user = userEvent.setup();
    renderAt(<FooterEditor />);
    await screen.findByText("Discord");
    await user.click(screen.getAllByTitle("Move down")[0]);
    await waitFor(() =>
      expect(screen.getAllByText(/^(Discord|Twitter)$/).map((n) => n.textContent)).toEqual(["Twitter", "Discord"])
    );
  });
});
