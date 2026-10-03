import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderAt } from "../test/render";

const auth = vi.hoisted(() => ({ value: { user: null, isAdmin: false, isSecondaryAdmin: false } }));
const perms = vi.hoisted(() => ({ granted: new Set() }));
const branding = vi.hoisted(() => ({ save: vi.fn() }));
vi.mock("../hooks/useAuth", () => ({ default: () => auth.value }));
vi.mock("../hooks/useStaffPermissions", () => ({ default: () => ({ can: (k) => perms.granted.has(k) }) }));
vi.mock("../hooks/useBranding", () => ({
  DEFAULT_LOGO: "📖",
  default: () => ({ name: "My Manga Site", logo: "📚", tagline: "", save: branding.save }),
}));
vi.mock("./NotificationBell", () => ({ default: () => null }));
vi.mock("./FunctionGate", () => ({ default: ({ children }) => children }));
vi.mock("./ThemeToggle", () => ({ default: () => null }));

import Navbar from "./Navbar";

const PENCIL = "Change website name & picture/favicon";

describe("Navbar branding", () => {
  beforeEach(() => {
    auth.value = { user: null, isAdmin: false, isSecondaryAdmin: false };
    perms.granted = new Set();
    branding.save.mockReset();
  });

  it("shows the site's saved name and logo to a guest, with no pencil", () => {
    renderAt(<Navbar />);
    expect(screen.getByText("My Manga Site")).toBeInTheDocument();
    expect(screen.getByText("📚")).toBeInTheDocument();
    expect(screen.queryByTitle(PENCIL)).not.toBeInTheDocument();
  });

  it("gives a signed-in reader no pencil either", () => {
    auth.value = { user: { id: 5, username: "reader" }, isAdmin: false, isSecondaryAdmin: false };
    renderAt(<Navbar />);
    expect(screen.queryByTitle(PENCIL)).not.toBeInTheDocument();
  });

  it("gives the branding power the pencil, and saves on the server", async () => {
    auth.value = { user: { id: 1, username: "owner" }, isAdmin: true, isSecondaryAdmin: true };
    perms.granted = new Set(["configure_branding"]);
    branding.save.mockResolvedValue({});
    renderAt(<Navbar />);
    fireEvent.click(screen.getByTitle(PENCIL));
    fireEvent.click(screen.getByRole("button", { name: /Save Changes/ }));
    await vi.waitFor(() => expect(branding.save).toHaveBeenCalledWith({ name: "My Manga Site", logo_url: "📚" }));
  });

  it("says why when the server refuses the change", async () => {
    auth.value = { user: { id: 1, username: "owner" }, isAdmin: true, isSecondaryAdmin: true };
    perms.granted = new Set(["configure_branding"]);
    branding.save.mockRejectedValue(Object.assign(new Error("x"), { code: "REVERIFICATION_REQUIRED" }));
    renderAt(<Navbar />);
    fireEvent.click(screen.getByTitle(PENCIL));
    fireEvent.click(screen.getByRole("button", { name: /Save Changes/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("authenticator code");
  });
});
