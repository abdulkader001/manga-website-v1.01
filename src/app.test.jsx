import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";

// Only the routing is under test: every page is a stub.
vi.mock("./components/Homepage", () => ({ default: () => <p>home page</p> }));
vi.mock("./pages/NotFound", () => ({ default: () => <p>not found</p> }));
vi.mock("./components/AuthGuard", () => ({ default: ({ children }) => children }));

import { AppRoutes } from "./app";

describe("sign-in landing (plan.md P0-4)", () => {
  it("sends the old Google / Microsoft landing address to the home page", async () => {
    render(
      <MemoryRouter initialEntries={["/auth/magic-complete"]}>
        <AppRoutes />
      </MemoryRouter>
    );
    expect(await screen.findByText("home page")).toBeTruthy();
    expect(screen.queryByText("not found")).toBeNull();
  });
});
