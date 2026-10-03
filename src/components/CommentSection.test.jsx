import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderAt } from "../test/render";

const api = vi.hoisted(() => ({ comments: { list: vi.fn(), create: vi.fn() } }));
vi.mock("../services/api", () => ({ default: api }));
vi.mock("../hooks/useAuth", () => ({ default: () => ({ user: { id: 1, username: "me" } }) }));

import CommentSection from "./CommentSection";

describe("CommentSection", () => {
  beforeEach(() => {
    api.comments.list.mockReset();
    api.comments.create.mockReset();
  });

  it("shows the author's username and likes as the API sends them", async () => {
    api.comments.list.mockResolvedValue({
      items: [{ id: 1, username: "shadow_monarch", content: "Great chapter", like_count: 4, created_at: null }],
    });
    renderAt(<CommentSection targetType="manga" targetId={1} />);
    expect(await screen.findByText("shadow_monarch")).toBeInTheDocument();
    expect(screen.getByText("+4")).toBeInTheDocument();
    expect(screen.queryByText("Reader")).not.toBeInTheDocument();
  });

  it("says when a removed comment was removed", async () => {
    api.comments.list.mockResolvedValue({
      items: [{ id: 2, username: "x", content: null, removed: true, like_count: 0 }],
    });
    renderAt(<CommentSection targetType="manga" targetId={1} />);
    expect(await screen.findByText("Removed by a moderator.")).toBeInTheDocument();
  });

  it("keeps the text and shows why a comment could not be posted", async () => {
    api.comments.list.mockResolvedValue({ items: [] });
    api.comments.create.mockRejectedValue(new Error("Comments are switched off."));
    renderAt(<CommentSection targetType="manga" targetId={1} />);
    const box = await screen.findByPlaceholderText("Join the discussion...");
    fireEvent.change(box, { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: "Post Comment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Comments are switched off.");
    expect(box).toHaveValue("hello");
  });
});
