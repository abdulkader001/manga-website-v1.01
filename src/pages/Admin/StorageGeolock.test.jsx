import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { renderAt } from "../../test/render";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() }));
const apiFetch = vi.hoisted(() => vi.fn());
vi.mock("../../services/api", () => ({ default: api, apiFetch, BASE_URL: "/api/v1" }));

import StorageBackups, { formatBytes } from "./StorageBackups";
import Geolock, { countryName, flag } from "./Geolock";
import RegionGate from "../../components/RegionGate";

const overview = {
  settings: { schedule_enabled: true, weekday: 6, hour_utc: 3, keep: 2, include_images: true, encrypted: true, next_run: "2026-10-04T03:00+00:00" },
  storage: { connected: false },
  status: { state: "idle" },
  disk: { free: 50 * 1024 ** 3, total: 100 * 1024 ** 3, backups: 3 * 1024 ** 2 },
  backups: [
    { name: "backup-20261002-030000.zip.enc", size: 3 * 1024 ** 2, created_at: "2026-10-02T03:00:00+00:00", trigger: "scheduled", includes_images: true, encrypted: true, remote: { uploaded: true } },
  ],
};

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  apiFetch.mockReset();
});

describe("Storage & Backups", () => {
  it("lists backups with download links and needs RESTORE typed to restore", async () => {
    api.get.mockResolvedValue(overview);
    api.post.mockResolvedValue({ queued: true });
    renderAt(<StorageBackups />);
    expect(await screen.findByText("backup-20261002-030000.zip.enc")).toBeInTheDocument();
    expect(screen.getByText("Copied to storage")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Download/ })).toHaveAttribute(
      "href",
      "/api/v1/admin/backups/files/backup-20261002-030000.zip.enc"
    );

    fireEvent.click(screen.getByRole("button", { name: "Restore" }));
    const dialog = screen.getByRole("dialog");
    const go = Array.from(dialog.querySelectorAll("button")).find((b) => b.textContent === "Restore");
    expect(go).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Type RESTORE/), { target: { value: "RESTORE" } });
    expect(go).not.toBeDisabled();
    await act(async () => fireEvent.click(go));
    expect(api.post).toHaveBeenCalledWith("/admin/backups/files/backup-20261002-030000.zip.enc/restore", {
      confirm: "RESTORE",
      password: undefined,
    });
  });

  it("formats sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(3 * 1024 ** 2)).toBe("3.0 MB");
    expect(formatBytes(50 * 1024 ** 3)).toBe("50.0 GB");
  });
});

describe("Geolock", () => {
  const geo = {
    enabled: false,
    blocked: [],
    source: "geoip",
    sources: ["geoip", "cloudflare"],
    countries: ["BD", "CA", "CN", "JP", "US"],
    database: { installed: true, type: "DBIP-Country-Lite", built_at: "2026-10-01" },
    your_country: "BD",
    attribution: { text: "IP Geolocation by DB-IP", url: "https://db-ip.com" },
  };

  it("ticks countries and saves them", async () => {
    api.get.mockResolvedValue(geo);
    api.put.mockImplementation(async (_p, body) => ({ ...geo, ...body }));
    renderAt(<Geolock />);
    await screen.findByText(/You are in/);
    fireEvent.click(screen.getByLabelText("Geolock on"));
    fireEvent.click(screen.getByRole("button", { name: "+ North America" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Japan/ }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save" })));
    expect(api.put).toHaveBeenCalledWith("/admin/geolock", {
      enabled: true,
      blocked: ["CA", "JP", "MX", "US"],
      source: "geoip",
      confirm_self_block: false,
    });
  });

  it("asks before locking the admin out, then confirms", async () => {
    api.get.mockResolvedValue({ ...geo, blocked: ["BD"], enabled: true });
    const lockout = Object.assign(new Error("This blocks BD, where you are now"), {
      body: { error: { details: { reason: "would_block_you" } } },
    });
    api.put.mockRejectedValueOnce(lockout).mockResolvedValueOnce({ ...geo, blocked: ["BD"], enabled: true });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    renderAt(<Geolock />);
    await screen.findByText(/You are in/);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save" })));
    await waitFor(() => expect(api.put).toHaveBeenCalledTimes(2));
    expect(confirm.mock.calls[0][0]).toMatch(/geolock-off/);
    expect(api.put.mock.calls[1][1].confirm_self_block).toBe(true);
    confirm.mockRestore();
  });

  it("names countries and draws flags", () => {
    expect(countryName("JP")).toBe("Japan");
    expect(flag("JP")).toBe("🇯🇵");
  });
});

describe("RegionGate", () => {
  it("shows the site, and the notice when the server answers 451", async () => {
    apiFetch.mockResolvedValue({ status: 200 });
    const { unmount } = render(<RegionGate>site</RegionGate>);
    expect(screen.getByText("site")).toBeInTheDocument();
    unmount();

    apiFetch.mockResolvedValue({ status: 451 });
    render(<RegionGate>site</RegionGate>);
    expect(await screen.findByText("Not available in your country")).toBeInTheDocument();
  });

  it("switches to the notice when any API call reports the block", async () => {
    apiFetch.mockResolvedValue({ status: 200 });
    render(<RegionGate>site</RegionGate>);
    await act(async () => window.dispatchEvent(new Event("region-blocked")));
    expect(screen.getByText("Not available in your country")).toBeInTheDocument();
  });
});
