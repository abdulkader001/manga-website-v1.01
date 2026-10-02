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
    roles: { admins: vi.fn(), limits: vi.fn(), saveLimits: vi.fn(), makeAdmin: vi.fn(), setSuccessors: vi.fn() },
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
  Object.values(api.admin.roles).forEach((fn) => fn.mockReset());
  api.admin.roles.admins.mockResolvedValue({ max_admins: 2, pool: 50, pool_used: 50, admins: [], sub_admins: [] });
  api.admin.roles.limits.mockResolvedValue({ blocked: [], always_blocked: [] });
  api.admin.users.mockResolvedValue([{ id: 7, name: "Rin", role: "secondary_admin", email: "rin@example.com" }]);
  p.catalogue.mockResolvedValue(catalogue);
  p.presets.mockResolvedValue({ presets: [] });
  p.managed.mockResolvedValue({ people: [{ user_id: 7, admin: false, authenticator: true }] });
  p.effective.mockResolvedValue({
    permissions: [
      { key: "handle_reports", effective: true, state: "inherited" },
      { key: "manage_backups", effective: false, state: "inherited" },
    ],
  });
  p.succession.mockResolvedValue({
    enabled: false,
    inactive_days: 60,
    rules: { max_admins: 2, window_days: 30 },
    admins: [],
    candidates: [],
  });
  p.setOverrides.mockResolvedValue({});
});

describe("Role Management", () => {
  it("asks the owner for their code before switching on a site-owner power for an Admin", async () => {
    perms.value = { isMainAdmin: true, can: () => true, isLoading: false };
    api.admin.users.mockResolvedValue([{ id: 7, name: "Rin", role: "co_admin", email: "rin@example.com" }]);
    api.admin.permissions.effective.mockResolvedValue({
      permissions: [
        { key: "handle_reports", effective: true, state: "inherited", role_default: true },
        { key: "manage_backups", effective: false, state: "revoked", role_default: true },
      ],
    });
    renderAt(<RoleManagement />);
    fireEvent.click(await screen.findByRole("switch", { name: "Manage backups" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "123456" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Continue" })));
    expect(api.admin.permissions.setOverrides).toHaveBeenCalledWith(7, [{ permission: "manage_backups", state: "granted" }], "123456");
    // Switching one off needs no code, and is a real "revoked" for an Admin.
    await act(async () => fireEvent.click(screen.getByRole("switch", { name: "Handle reports" })));
    expect(api.admin.permissions.setOverrides).toHaveBeenLastCalledWith(7, [{ permission: "handle_reports", state: "revoked" }], undefined);
    expect(await screen.findByText("Automatic succession")).toBeInTheDocument();
    expect(await screen.findByText("What sub-admins may hold")).toBeInTheDocument();
  });

  it("an Admin can't touch site-owner powers, the ceiling or succession settings", async () => {
    perms.value = { isMainAdmin: false, isAdminTier: true, can: (k) => k === "manage_roles", isLoading: false };
    api.admin.permissions.mine.mockResolvedValue({ user_id: 99, role: "admin" });
    renderAt(<RoleManagement />);
    expect(await screen.findByRole("switch", { name: "Manage backups" })).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Handle reports" })).not.toBeDisabled();
    expect(await screen.findByText("Your Admin seat")).toBeInTheDocument();
    expect(screen.queryByText("Automatic succession")).not.toBeInTheDocument();
    expect(screen.queryByText("What sub-admins may hold")).not.toBeInTheDocument();
    expect(api.admin.permissions.succession).not.toHaveBeenCalled();
    expect(api.admin.roles.limits).not.toHaveBeenCalled();
  });

  it("shows a power the owner's ceiling blocks as locked", async () => {
    perms.value = { isMainAdmin: false, isAdminTier: true, can: () => true, isLoading: false };
    api.admin.permissions.mine.mockResolvedValue({ user_id: 99, role: "admin" });
    api.admin.permissions.effective.mockResolvedValue({
      permissions: [{ key: "handle_reports", effective: false, state: "blocked", role_default: true }],
    });
    renderAt(<RoleManagement />);
    expect(await screen.findByText("blocked by owner")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Handle reports" })).toBeDisabled();
  });

  it("the owner makes an Admin with their code", async () => {
    perms.value = { isMainAdmin: true, can: () => true, isLoading: false };
    api.admin.roles.admins.mockResolvedValue({
      max_admins: 2,
      pool: 50,
      pool_used: 25,
      admins: [],
      sub_admins: [{ user_id: 7, name: "Rin", blocked_by: [] }],
    });
    api.admin.roles.makeAdmin.mockResolvedValue({});
    renderAt(<RoleManagement />);
    fireEvent.change(await screen.findByLabelText("Sub-admin to make an Admin"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Make Admin" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "654321" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Continue" })));
    expect(api.admin.roles.makeAdmin).toHaveBeenCalledWith(7, "654321");
  });
});
