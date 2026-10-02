import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const api = vi.hoisted(() => ({ config: { siteAccess: vi.fn() } }));
vi.mock("../services/api", () => ({ default: api }));
const auth = vi.hoisted(() => ({ value: {} }));
vi.mock("../hooks/useAuth", () => ({ default: () => auth.value }));

import AuthGuard from "./AuthGuard";

const page = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={["/manga/1"]}>
        <Routes>
          <Route path="/login" element={<p>login page</p>} />
          <Route
            path="/manga/:id"
            element={
              <AuthGuard followSiteSetting>
                <p>manga page</p>
              </AuthGuard>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );

describe("AuthGuard and the sign-in-required switch", () => {
  beforeEach(() => {
    auth.value = { user: null, isLoading: false };
    api.config.siteAccess.mockReset();
  });

  it("lets guests read when sign-in is not required", async () => {
    api.config.siteAccess.mockResolvedValue({ loginRequired: false });
    page();
    expect(await screen.findByText("manga page")).toBeInTheDocument();
  });

  it("sends guests to the login page when sign-in is required", async () => {
    api.config.siteAccess.mockResolvedValue({ loginRequired: true });
    page();
    expect(await screen.findByText("login page")).toBeInTheDocument();
    expect(screen.queryByText("manga page")).not.toBeInTheDocument();
  });

  it("sends guests to the login page when the setting can't be read", async () => {
    api.config.siteAccess.mockRejectedValue(new Error("offline"));
    page();
    // The guard retries once before it gives up, so allow for that.
    expect(await screen.findByText("login page", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(screen.queryByText("manga page")).not.toBeInTheDocument();
  });

  it("never blocks a signed-in reader", async () => {
    auth.value = {
      user: { profile_completed: true, birth_date: "2000-01-01", name: "A", username: "a" },
      isLoading: false,
    };
    api.config.siteAccess.mockResolvedValue({ loginRequired: true });
    page();
    expect(await screen.findByText("manga page")).toBeInTheDocument();
  });
});
