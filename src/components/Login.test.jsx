import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../test/render";

const requestMagicLink = vi.fn();
vi.mock("../services/api", () => ({
  default: { auth: { requestMagicLink: (...a) => requestMagicLink(...a) } },
  apiFetch: vi.fn(),
}));
vi.mock("../hooks/useAuth", () => ({
  default: () => ({ login: vi.fn(), refetchUser: vi.fn() }),
}));

import Login from "./Login";

describe("Login", () => {
  beforeEach(() => {
    requestMagicLink.mockReset();
    requestMagicLink.mockResolvedValue({});
  });

  it("offers the sign-in choices", () => {
    renderAt(<Login />);
    expect(screen.getByText(/Welcome to Manga World/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("you@example.com")).toBeInTheDocument();
  });

  it("rejects an email without @ and does not call the API", async () => {
    const user = userEvent.setup();
    const { container } = renderAt(<Login />);
    await user.type(screen.getByPlaceholderText("you@example.com"), "nobody");
    // The input is type=email, so submit the form directly (jsdom would
    // otherwise block it on native validation).
    container.querySelector("form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await waitFor(() => expect(screen.getByText(/valid email address/i)).toBeInTheDocument());
    expect(requestMagicLink).not.toHaveBeenCalled();
  });

  it("requests a magic link and shows the confirmation", async () => {
    requestMagicLink.mockResolvedValue({});
    const user = userEvent.setup();
    renderAt(<Login />);
    await user.type(screen.getByPlaceholderText("you@example.com"), "reader@example.com");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(requestMagicLink).toHaveBeenCalledWith("reader@example.com"));
    expect(await screen.findByText(/We sent a verification link to/i)).toBeInTheDocument();
    expect(screen.getByText("reader@example.com")).toBeInTheDocument();
  });

  it("shows the server's message when the request fails", async () => {
    requestMagicLink.mockImplementation(async () => {
      throw new Error("Too many requests");
    });
    const user = userEvent.setup();
    renderAt(<Login />);
    await user.type(screen.getByPlaceholderText("you@example.com"), "reader@example.com");
    await user.keyboard("{Enter}");
    expect(await screen.findByText("Too many requests")).toBeInTheDocument();
  });
});
