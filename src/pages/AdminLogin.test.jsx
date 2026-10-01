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
      .mockImplementationOnce(() => reply({ open: true }))
      .mockImplementationOnce(() => reply({ step: "enrol", secret: "ABCDEF", otpauth_uri: "otpauth://totp/x" }))
      .mockImplementationOnce(() => reply({ step: "done" }));
    const user = userEvent.setup();
    renderAt(<AdminLogin />);

    await user.type(await screen.findByPlaceholderText("you@example.com"), "owner@example.com");
    await user.type(screen.getByPlaceholderText("One-time admin password"), "long password here");
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
      .mockImplementationOnce(() => reply({ open: true }))
      .mockImplementationOnce(() => reply({ error: { message: "Email, password or code is not right." } }, 401));
    const user = userEvent.setup();
    renderAt(<AdminLogin />);
    await user.type(await screen.findByPlaceholderText("you@example.com"), "owner@example.com");
    await user.type(screen.getByPlaceholderText("One-time admin password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Email, password or code is not right.")).toBeInTheDocument();
  });

  it("is a plain 'not found' page once the one-time password is used (or none is set)", async () => {
    apiFetch.mockImplementationOnce(() => reply({ error: { message: "Not found." } }, 404));
    renderAt(<AdminLogin />);
    await waitFor(() => expect(screen.queryByPlaceholderText("you@example.com")).not.toBeInTheDocument());
    expect(screen.queryByText(/Admin sign-in/)).not.toBeInTheDocument();
    expect(screen.queryByText(/one-time/i)).not.toBeInTheDocument();
  });

  it("turns into 'not found' if the page closes while it is open", async () => {
    apiFetch
      .mockImplementationOnce(() => reply({ open: true }))
      .mockImplementationOnce(() => reply({ error: { message: "Not found." } }, 404));
    const user = userEvent.setup();
    renderAt(<AdminLogin />);
    await user.type(await screen.findByPlaceholderText("you@example.com"), "owner@example.com");
    await user.type(screen.getByPlaceholderText("One-time admin password"), "long password here");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(screen.queryByPlaceholderText("you@example.com")).not.toBeInTheDocument());
  });
});
