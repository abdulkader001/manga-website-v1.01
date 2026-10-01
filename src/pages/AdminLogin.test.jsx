import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../test/render";

const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("../services/api", () => ({ default: {}, apiFetch }));

import AdminLogin from "./AdminLogin";

const reply = (body, status = 200) =>
  Promise.resolve({ ok: status < 400, status, json: () => Promise.resolve(body) });

describe("Admin sign-in", () => {
  beforeEach(() => {
    apiFetch.mockReset();
  });

  it("walks through password, authenticator setup, then signs in", async () => {
    const assign = vi.fn();
    Object.defineProperty(window, "location", { value: { ...window.location, assign }, writable: true });
    apiFetch
      .mockImplementationOnce(() => reply({ enabled: true }))
      .mockImplementationOnce(() => reply({ step: "enrol", secret: "ABCDEF", otpauth_uri: "otpauth://totp/x" }))
      .mockImplementationOnce(() => reply({ step: "done" }));
    const user = userEvent.setup();
    renderAt(<AdminLogin />);

    await user.type(screen.getByPlaceholderText("you@example.com"), "owner@example.com");
    await user.type(screen.getByPlaceholderText("Admin password"), "long password here");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    expect(await screen.findByText("ABCDEF")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Authenticator code"), "123456");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/admin"));
    const last = JSON.parse(apiFetch.mock.calls[2][1].body);
    expect(last).toEqual({ email: "owner@example.com", password: "long password here", code: "123456" });
  });

  it("shows the server's answer for a wrong password", async () => {
    apiFetch
      .mockImplementationOnce(() => reply({ enabled: true }))
      .mockImplementationOnce(() => reply({ error: { message: "Email, password or code is not right." } }, 401));
    const user = userEvent.setup();
    renderAt(<AdminLogin />);
    await user.type(screen.getByPlaceholderText("you@example.com"), "owner@example.com");
    await user.type(screen.getByPlaceholderText("Admin password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Email, password or code is not right.")).toBeInTheDocument();
  });

  it("explains how to set it up when the server has no admin password", async () => {
    apiFetch.mockImplementationOnce(() => reply({ enabled: false }));
    renderAt(<AdminLogin />);
    expect(await screen.findByText(/not set up on this server yet/)).toBeInTheDocument();
  });
});
