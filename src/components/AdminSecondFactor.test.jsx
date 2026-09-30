import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../test/render";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("../services/api", () => ({ default: api }));

import AdminSecondFactor from "./AdminSecondFactor";

const page = () => renderAt(<AdminSecondFactor><p>secret admin page</p></AdminSecondFactor>);

describe("Admin second factor gate", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
  });

  it("lets admins without a second factor straight in", async () => {
    api.get.mockResolvedValue({ enabled: false, unlocked: false, required: false });
    page();
    expect(await screen.findByText("secret admin page")).toBeInTheDocument();
  });

  it("asks for a code, then opens the page", async () => {
    api.get
      .mockResolvedValueOnce({ enabled: true, unlocked: false, required: false })
      .mockResolvedValueOnce({ enabled: true, unlocked: true, required: false });
    api.post.mockResolvedValue({ unlocked: true });
    const user = userEvent.setup();
    page();
    expect(await screen.findByText(/Confirm it/)).toBeInTheDocument();
    expect(screen.queryByText("secret admin page")).not.toBeInTheDocument();
    await user.type(screen.getByRole("textbox"), "123456");
    await user.click(screen.getByRole("button", { name: /Continue/i }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/admin/2fa/verify", { code: "123456" }));
    expect(await screen.findByText("secret admin page")).toBeInTheDocument();
  });

  it("keeps the page closed after a wrong code", async () => {
    api.get.mockResolvedValue({ enabled: true, unlocked: false, required: false });
    api.post.mockImplementation(async () => {
      throw new Error("That code is not valid.");
    });
    const user = userEvent.setup();
    page();
    await user.type(await screen.findByRole("textbox"), "000000");
    await user.click(screen.getByRole("button", { name: /Continue/i }));
    expect(await screen.findByText("That code is not valid.")).toBeInTheDocument();
    expect(screen.queryByText("secret admin page")).not.toBeInTheDocument();
  });

  it("makes a main admin enrol first when it is required", async () => {
    api.get.mockResolvedValue({ enabled: false, unlocked: false, required: true });
    page();
    expect(await screen.findByText(/Set up two-step sign-in/)).toBeInTheDocument();
    expect(screen.queryByText("secret admin page")).not.toBeInTheDocument();
  });
});
