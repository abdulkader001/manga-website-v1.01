import "@testing-library/jest-dom";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { renderWithProviders } from "../../test-utils/renderWithProviders";

import RoleManagement from "./RoleManagement";
import api from "../../services/api";
import useAuth from "../../hooks/useAuth";

jest.mock("../../services/api", () => {
  const users = jest.fn();
  const promoteSecondary = jest.fn();
  const demoteSecondary = jest.fn();
  const demoteMain = jest.fn();
  const promoteSecondaryByEmail = jest.fn();
  const demoteSecondaryByEmail = jest.fn();
  const catalogue = jest.fn();
  const effective = jest.fn();
  const setOverrides = jest.fn();

  return {
    __esModule: true,
    default: {
      admin: {
        users,
        promoteSecondary,
        demoteSecondary,
        demoteMain,
        promoteSecondaryByEmail,
        demoteSecondaryByEmail,
        permissions: {
          catalogue,
          effective,
          setOverrides,
        },
      },
    },
  };
});

jest.mock("../../hooks/useAuth", () => ({
  __esModule: true,
  default: jest.fn(),
}));

const mockUseAuth = useAuth;

beforeEach(() => {
  jest.clearAllMocks();
  mockUseAuth.mockReturnValue({
    isAdmin: true,
    user: { id: 1, email: "main@example.com" },
  });
  api.admin.users.mockResolvedValue([
    { id: 1, email: "main@example.com", role: "admin", is_main_admin: true },
    { id: 2, email: "secondary@example.com", role: "secondary_admin", is_secondary_admin: true },
    { id: 3, email: "reader@example.com", role: "user" },
  ]);
  api.admin.promoteSecondary.mockResolvedValue({ ok: true });
  api.admin.demoteSecondary.mockResolvedValue({ ok: true });
  api.admin.promoteSecondaryByEmail.mockResolvedValue({ ok: true });
  api.admin.demoteSecondaryByEmail.mockResolvedValue({ ok: true });
  api.admin.permissions.catalogue.mockResolvedValue({ permissions: [] });
  api.admin.permissions.effective.mockResolvedValue({ permissions: [] });
  api.admin.permissions.setOverrides.mockResolvedValue({ permissions: [] });
});

function waitForUsers() {
  return waitFor(() => expect(api.admin.users).toHaveBeenCalled());
}

test("renders secondary admins without showing normal users", async () => {
  renderWithProviders(<RoleManagement />);

  await waitForUsers();

  const secondarySection = await screen.findByTestId("secondary-admins");

  expect(within(secondarySection).getByText("secondary@example.com")).toBeInTheDocument();
  expect(screen.queryByTestId("normal-users")).not.toBeInTheDocument();
});

test("promotes and demotes Gmail addresses through the forms", async () => {
  renderWithProviders(<RoleManagement />);

  await waitForUsers();

  const promoteInput = screen.getByLabelText(/promote gmail address/i);
  fireEvent.change(promoteInput, { target: { value: "Helper@GMAIL.com" } });
  fireEvent.submit(screen.getByTestId("promote-form"));

  await waitFor(() => expect(api.admin.promoteSecondaryByEmail).toHaveBeenCalledWith("helper@gmail.com"));

  const demoteInput = screen.getByLabelText(/demote gmail address/i);
  fireEvent.change(demoteInput, { target: { value: "old-admin@gmail.com" } });
  fireEvent.submit(screen.getByTestId("demote-form"));

  await waitFor(() => expect(api.admin.demoteSecondaryByEmail).toHaveBeenCalledWith("old-admin@gmail.com"));
});

test("toggling a permission override for a sub-admin calls the real endpoint and reflects the new state", async () => {
  api.admin.permissions.catalogue.mockResolvedValue({
    permissions: [
      {
        key: "rescrape_chapter",
        group: "Content and series",
        defaults: { permanent_admin: true, admin: true, secondary_admin: true, moderator: true },
      },
    ],
  });
  api.admin.permissions.effective.mockResolvedValue({
    user_id: 2,
    role: "secondary_admin",
    modified_count: 0,
    permissions: [
      { key: "rescrape_chapter", effective: true, state: "inherited", role_default: true },
    ],
  });

  renderWithProviders(<RoleManagement />);
  await waitForUsers();

  const select = screen.getByLabelText(/sub-admin or moderator/i);
  await within(select).findByText(/secondary@example\.com/i);
  fireEvent.change(select, { target: { value: "2" } });

  await waitFor(() => expect(api.admin.permissions.effective).toHaveBeenCalledWith("2"));

  const toggle = await screen.findByLabelText("rescrape_chapter override");
  expect(toggle).toHaveValue("inherited");

  api.admin.permissions.setOverrides.mockResolvedValue({
    user_id: 2,
    modified_count: 1,
    permissions: [
      { key: "rescrape_chapter", effective: false, state: "revoked", role_default: true },
    ],
  });
  api.admin.permissions.effective.mockResolvedValue({
    user_id: 2,
    role: "secondary_admin",
    modified_count: 1,
    permissions: [
      { key: "rescrape_chapter", effective: false, state: "revoked", role_default: true },
    ],
  });

  fireEvent.change(toggle, { target: { value: "revoked" } });

  await waitFor(() =>
    expect(api.admin.permissions.setOverrides).toHaveBeenCalledWith("2", [
      { permission: "rescrape_chapter", state: "revoked" },
    ])
  );

  await waitFor(() => expect(toggle).toHaveValue("revoked"));
  expect(screen.getByText(/currently blocked/i)).toBeInTheDocument();
});
