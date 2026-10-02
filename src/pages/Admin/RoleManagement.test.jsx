import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, screen, within } from "@testing-library/react";
import { renderAt } from "../../test/render";

const perms = vi.hoisted(() => ({ value: { isMainAdmin: true, can: () => true, isLoading: false } }));
vi.mock("../../hooks/useStaffPermissions", () => ({ default: () => perms.value }));

const api = vi.hoisted(() => ({
  admin: {
    users: vi.fn(),
    promoteSecondaryByEmail: vi.fn(),
    demoteSecondary: vi.fn(),
    permissions: {
      catalogue: vi.fn(),
      presets: vi.fn(),
      effective: vi.fn(),
      setOverrides: vi.fn(),
      reset: vi.fn(),
      applyPreset: vi.fn(),
      managed: vi.fn(),
      mine: vi.fn(),
      succession: vi.fn(),
      saveSuccession: vi.fn(),
    },
  },
  post: vi.fn(),
}));
vi.mock("../../services/api", () => ({ default: api }));

import RoleManagement from "./RoleManagement";

const catalogue = {
  permissions: [
    { key: "handle_reports", group: "Community and moderation", description: "Reports", owner_power: false },
    { key: "manage_backups", group: "Site owner powers", description: "Backups.", owner_power: true },
  ],
};

beforeEach(() => {
  const p = api.admin.permissions;
  Object.values(p).forEach((fn) => fn.mockReset());
  api.admin.users.mockResolvedValue([{ id: 7, name: "Rin", role: "secondary_admin", email: "rin@example.com" }]);
  p.catalogue.mockResolvedValue(catalogue);
  p.presets.mockResolvedValue({ presets: [] });
  p.managed.mockResolvedValue({ people: [{ user_id: 7, deputy: false, authenticator: true }] });
  p.effective.mockResolvedValue({
    permissions: [
      { key: "handle_reports", effective: true, state: "inherited" },
      { key: "manage_backups", effective: false, state: "inherited" },
    ],
  });
  p.succession.mockResolvedValue({
    enabled: false,
    inactive_days: 60,
    rules: { max_deputies: 2, window_days: 30, min_active_days: 20, min_work_days: 10, min_tenure_days: 30 },
    deputies: [],
    candidates: [{ user_id: 7, name: "Rin", active_days: 25, work_days: 12, admin_for_days: 90, blocked_by: [] }],
  });
  p.setOverrides.mockResolvedValue({});
});

describe("Role Management", () => {
  it("asks the owner for their code before giving a site-owner power", async () => {
    perms.value = { isMainAdmin: true, can: () => true, isLoading: false };
    renderAt(<RoleManagement />);
    const toggle = await screen.findByRole("switch", { name: "Manage backups" });
    fireEvent.click(toggle);
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "123456" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Continue" })));
    expect(api.admin.permissions.setOverrides).toHaveBeenCalledWith(7, [{ permission: "manage_backups", state: "granted" }], "123456");
    // Everyday powers need no code.
    await act(async () => fireEvent.click(screen.getByRole("switch", { name: "Handle reports" })));
    expect(api.admin.permissions.setOverrides).toHaveBeenLastCalledWith(7, [{ permission: "handle_reports", state: "revoked" }], undefined);
    expect(await screen.findByText("Automatic succession")).toBeInTheDocument();
  });

  it("a deputy with Role Management can't touch site-owner powers or see succession", async () => {
    perms.value = { isMainAdmin: false, can: (k) => k === "manage_roles", isLoading: false };
    api.admin.permissions.mine.mockResolvedValue({ user_id: 99 });
    renderAt(<RoleManagement />);
    expect(await screen.findByRole("switch", { name: "Manage backups" })).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Handle reports" })).not.toBeDisabled();
    expect(screen.queryByText("Automatic succession")).not.toBeInTheDocument();
    expect(api.admin.permissions.succession).not.toHaveBeenCalled();
  });

  it("shows a deputy's row as protected to another sub-admin", async () => {
    perms.value = { isMainAdmin: false, can: () => true, isLoading: false };
    api.admin.permissions.mine.mockResolvedValue({ user_id: 99 });
    api.admin.permissions.managed.mockResolvedValue({ people: [{ user_id: 7, deputy: true, authenticator: true }] });
    renderAt(<RoleManagement />);
    expect(await screen.findByText("Deputy")).toBeInTheDocument();
    expect(await screen.findByText(/Only the site owner can change a deputy/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
  });
});
