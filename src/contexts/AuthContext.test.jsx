import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const mocks = vi.hoisted(() => ({
  me: vi.fn(),
  refreshSession: vi.fn(),
}));
vi.mock("../services/api", () => ({
  default: { auth: { me: mocks.me } },
  refreshSession: mocks.refreshSession,
  setSessionActive: vi.fn(),
}));

import { AuthProvider, useAuthContext } from "./AuthContext";

function Who() {
  const { user, isLoading } = useAuthContext();
  if (isLoading) return <p>loading</p>;
  return <p>{user ? `signed in as ${user.username}` : "guest"}</p>;
}

const expired = () => Object.assign(new Error("expired"), { status: 401 });

describe("AuthProvider", () => {
  beforeEach(() => {
    mocks.me.mockReset();
    mocks.refreshSession.mockReset();
  });

  it("renews an expired access token for someone signed in on this browser", async () => {
    localStorage.setItem("mw_had_session", "1");
    mocks.me.mockRejectedValueOnce(expired()).mockResolvedValueOnce({ id: 2, username: "owner" });
    mocks.refreshSession.mockResolvedValue(true);
    render(<AuthProvider><Who /></AuthProvider>);
    expect(await screen.findByText("signed in as owner")).toBeInTheDocument();
    expect(mocks.refreshSession).toHaveBeenCalledTimes(1);
  });

  it("never tries to renew for a guest", async () => {
    mocks.me.mockRejectedValue(expired());
    render(<AuthProvider><Who /></AuthProvider>);
    expect(await screen.findByText("guest")).toBeInTheDocument();
    expect(mocks.refreshSession).not.toHaveBeenCalled();
  });

  it("forgets the session when the renewal is refused too", async () => {
    localStorage.setItem("mw_had_session", "1");
    mocks.me.mockRejectedValue(expired());
    mocks.refreshSession.mockResolvedValue(false);
    render(<AuthProvider><Who /></AuthProvider>);
    expect(await screen.findByText("guest")).toBeInTheDocument();
    expect(localStorage.getItem("mw_had_session")).toBeNull();
  });
});
