import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../../test/render";

const list = vi.fn();
const resolve = vi.fn();
vi.mock("../../services/api", () => ({
  default: {
    admin: {
      errorReports: {
        list: (...a) => list(...a),
        resolve: (...a) => resolve(...a),
        reopen: vi.fn(),
        clearResolved: vi.fn(),
      },
    },
  },
}));

import ErrorReport, { timeAgo } from "./ErrorReport";

const entry = {
  id: 7,
  source: "server",
  kind: "OperationalError",
  message: 'relation "error_reports" does not exist',
  location: "GET /api/v1/manga/{id}",
  stack: "Traceback ...",
  category: "database",
  cause: "The database is missing a table.",
  fix: "Run alembic upgrade head.",
  count: 12,
  first_seen: new Date().toISOString(),
  last_seen: new Date().toISOString(),
  resolved: false,
};
const payload = (items) => ({
  items,
  summary: { open: items.length, resolved: 0, last_24h: items.length, by_source: { server: items.length, worker: 0, browser: 0 } },
});

describe("Error Report page", () => {
  beforeEach(() => {
    list.mockReset();
    resolve.mockReset();
  });

  it("shows each error with its likely cause and fix", async () => {
    list.mockResolvedValue(payload([entry]));
    renderAt(<ErrorReport />);
    expect(await screen.findByText("OperationalError")).toBeInTheDocument();
    expect(screen.getByText("The database is missing a table.")).toBeInTheDocument();
    expect(screen.getByText("Run alembic upgrade head.")).toBeInTheDocument();
    expect(screen.getByText("12×")).toBeInTheDocument();
    expect(list).toHaveBeenCalledWith({ status: "open", source: undefined });
  });

  it("marks an error fixed and reloads", async () => {
    list.mockResolvedValueOnce(payload([entry])).mockResolvedValue(payload([]));
    resolve.mockResolvedValue({ ...entry, resolved: true });
    renderAt(<ErrorReport />);
    await userEvent.click(await screen.findByRole("button", { name: "Mark fixed" }));
    expect(resolve).toHaveBeenCalledWith(7);
    await waitFor(() => expect(screen.getByText(/No open errors/)).toBeInTheDocument());
  });

  it("says how long ago in plain words", () => {
    const now = Date.parse("2026-10-03T12:00:00Z");
    expect(timeAgo("2026-10-03T11:59:30Z", now)).toBe("just now");
    expect(timeAgo("2026-10-03T11:00:00Z", now)).toBe("1 h ago");
    expect(timeAgo(null, now)).toBe("—");
  });
});
