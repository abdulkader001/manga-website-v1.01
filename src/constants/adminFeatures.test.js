import { describe, expect, it } from "vitest";
import { ADMIN_FEATURE_LINKS, visibleAdminLinks } from "./adminFeatures";

const keys = (links) => links.map((l) => l.key).sort();

describe("admin hub tiles (F-97)", () => {
  it("shows the main admin every tile", () => {
    expect(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isAdmin: true, can: () => true })).toHaveLength(
      ADMIN_FEATURE_LINKS.length
    );
  });

  it("never shows a sub-admin a main-admin-only tile, even with the permission", () => {
    const shown = keys(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isSecondaryAdmin: true, can: () => true }));
    expect(shown).toEqual(["chapter-reports", "health", "series"]);
    for (const hidden of ["users", "ads", "roles", "settings", "api-management", "vault", "audit-report"]) {
      expect(shown).not.toContain(hidden);
    }
  });

  it("follows the sub-admin's toggles", () => {
    const can = (key) => key === "handle_reports";
    expect(keys(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isSecondaryAdmin: true, can }))).toEqual(["chapter-reports"]);
  });

  it("shows readers nothing", () => {
    expect(visibleAdminLinks(ADMIN_FEATURE_LINKS, { can: () => true })).toEqual([]);
  });
});
