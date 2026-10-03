import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderAt } from "../test/render";

const api = vi.hoisted(() => ({ auth: { consumeMagicLink: vi.fn() } }));
vi.mock("../services/api", () => ({ default: api }));
const refetchUser = vi.fn();
vi.mock("../hooks/useAuth", () => ({ default: () => ({ refetchUser }) }));

import MagicLinkConsume from "./MagicLinkConsume";

describe("MagicLinkConsume", () => {
  it("spends a sign-in link only once, even in StrictMode", async () => {
    api.auth.consumeMagicLink.mockResolvedValue({
      user: { profile_completed: true, birth_date: "2000-01-01", name: "A", username: "a" },
    });
    renderAt(
      <React.StrictMode>
        <MagicLinkConsume />
      </React.StrictMode>,
      { path: "/magic-link/tok123", route: "/magic-link/:token" }
    );
    expect(await screen.findByText(/Sign-in successful/)).toBeInTheDocument();
    expect(api.auth.consumeMagicLink).toHaveBeenCalledTimes(1);
    expect(api.auth.consumeMagicLink).toHaveBeenCalledWith("tok123");
  });
});
