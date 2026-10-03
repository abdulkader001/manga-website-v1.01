import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../../test/render";

const list = vi.fn();
const set = vi.fn();
vi.mock("../../services/api", () => ({
  default: { admin: { siteFunctions: { list: (...a) => list(...a), set: (...a) => set(...a) } } },
}));

import SiteFunctions from "./SiteFunctions";

const payload = (comments = true) => ({
  groups: ["Sign-in and access", "Reading and community"],
  functions: [
    { key: "sign_in_google", label: "Sign in with Google", group: "Sign-in and access", description: "d", enabled: true, warning: "At least one sign-in method must stay on." },
    { key: "comments", label: "Comments", group: "Reading and community", description: "d", enabled: comments, warning: "" },
  ],
});

describe("Site Functions page", () => {
  beforeEach(() => {
    list.mockReset();
    set.mockReset();
    vi.restoreAllMocks();
  });

  it("lists every function grouped, with its switch", async () => {
    list.mockResolvedValue(payload());
    renderAt(<SiteFunctions />);
    expect(await screen.findByText("Sign in with Google")).toBeInTheDocument();
    expect(screen.getByText("Reading and community")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Comments" })).toHaveAttribute("aria-checked", "true");
  });

  it("switches a function off and shows the new state from the server", async () => {
    list.mockResolvedValue(payload(true));
    set.mockResolvedValue(payload(false));
    const user = userEvent.setup();
    renderAt(<SiteFunctions />);
    await user.click(await screen.findByRole("switch", { name: "Comments" }));
    await waitFor(() => expect(set).toHaveBeenCalledWith("comments", false));
    await waitFor(() =>
      expect(screen.getByRole("switch", { name: "Comments" })).toHaveAttribute("aria-checked", "false")
    );
  });

  it("asks before switching off a function that carries a warning", async () => {
    list.mockResolvedValue(payload());
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    renderAt(<SiteFunctions />);
    await user.click(await screen.findByRole("switch", { name: "Sign in with Google" }));
    expect(confirm).toHaveBeenCalled();
    expect(set).not.toHaveBeenCalled();
  });

  it("shows the server's refusal, for example the last sign-in method", async () => {
    list.mockResolvedValue(payload());
    set.mockRejectedValue(new Error("At least one sign-in method must stay on, or nobody could sign in."));
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const user = userEvent.setup();
    renderAt(<SiteFunctions />);
    await user.click(await screen.findByRole("switch", { name: "Sign in with Google" }));
    expect(await screen.findByText(/or nobody could sign in/)).toBeInTheDocument();
  });
});
