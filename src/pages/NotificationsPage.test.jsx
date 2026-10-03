import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderAt } from "../test/render";

const api = vi.hoisted(() => ({
  notifications: { list: vi.fn(), markRead: vi.fn(), markAllRead: vi.fn(), remove: vi.fn() },
}));
vi.mock("../services/api", () => ({ default: api }));

import NotificationsPage from "./NotificationsPage";

// Shapes exactly as the server's Notification.to_dict() sends them.
const ITEMS = [
  {
    id: 1, type: "chapter.new", category: "reader", read: false,
    title: "Chapter 12 of Solo Story is available", body: "Chapter 12 of Solo Story is available",
    target_type: "series", target_id: "5", data: { series_id: 5 }, created_at: "2026-10-03T10:00:00",
  },
  {
    id: 2, type: "chapter.reported", category: "administrative", read: false,
    title: "Chapter report: broken_images", body: "Solo Story — chapter 3: pages missing",
    target_type: "chapter", target_id: "9", data: { manga_id: 5, report_type: "broken_images" },
    created_at: "2026-10-03T09:00:00",
  },
  {
    id: 3, type: "chapter.fix_completed", category: "administrative", read: true,
    title: "Chapter 3 was rescripted", body: "Refresh to see the fixed chapter.",
    target_type: "chapter", target_id: "9", data: { manga_id: 5 }, created_at: "2026-10-03T08:00:00",
  },
  {
    id: 4, type: "announcement", category: "reader", read: true,
    title: "Maintenance tonight", body: "", target_type: "announcement", target_id: "1", data: {},
    created_at: "2026-10-03T07:00:00",
  },
];

describe("Notifications & Chapter Alerts", () => {
  it("lists the server's chapter alerts under the Chapter Alerts tab with badges", async () => {
    api.notifications.list.mockResolvedValue({ items: ITEMS });
    renderAt(<NotificationsPage />);
    expect(await screen.findByText("Chapter 12 of Solo Story is available", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("New Chapter")).toBeInTheDocument();
    expect(screen.getByText("Broadcast")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Chapter Alerts & Issues/ }));
    expect(screen.getByText("Chapter report: broken_images")).toBeInTheDocument();
    expect(screen.getByText("Chapter 3 was rescripted")).toBeInTheDocument();
    expect(screen.getByText(/Resolved/)).toBeInTheDocument();
    expect(screen.getByText(/Broken Chapter/)).toBeInTheDocument();
    expect(screen.queryByText("Maintenance tonight")).not.toBeInTheDocument();
    expect(screen.queryByText(/No active chapter issues/)).not.toBeInTheDocument();
  });

  it("counts unread from the server's read flag", async () => {
    api.notifications.list.mockResolvedValue({ items: ITEMS });
    renderAt(<NotificationsPage />);
    await screen.findByText("New Chapter");
    fireEvent.click(screen.getByRole("button", { name: /Unread/ }));
    expect(screen.getByText("Chapter report: broken_images")).toBeInTheDocument();
    expect(screen.queryByText("Maintenance tonight")).not.toBeInTheDocument();
  });
});
