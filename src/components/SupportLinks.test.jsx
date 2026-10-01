import React from "react";
import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderAt } from "../test/render";

const api = vi.hoisted(() => ({ support: { get: vi.fn() } }));
vi.mock("../services/api", () => ({ default: api }));

import SupportLinks from "./SupportLinks";

describe("Support the site", () => {
  it("opens payment links safely and shows crypto with its network", async () => {
    api.support.get.mockResolvedValue({
      links: [
        { id: "a", kind: "link", platform: "kofi", label: "Ko-fi", url: "https://ko-fi.com/x" },
        { id: "b", kind: "crypto", network: "btc", label: "Bitcoin (BTC)", address: "bc1qxyz" },
      ],
    });
    renderAt(<SupportLinks />);
    const link = await screen.findByRole("link", { name: /Ko-fi/ });
    expect(link).toHaveAttribute("href", "https://ko-fi.com/x");
    expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(link).toHaveAttribute("target", "_blank");
    expect(screen.getByText("bc1qxyz")).toBeInTheDocument();
    expect(screen.getByText(/Send only on this network/)).toBeInTheDocument();
  });

  it("shows nothing when no links are set", async () => {
    api.support.get.mockResolvedValue({ links: [] });
    const { container } = renderAt(<SupportLinks />);
    await new Promise((r) => setTimeout(r, 0));
    expect(container).toBeEmptyDOMElement();
  });
});
