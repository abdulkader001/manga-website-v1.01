import { describe, expect, it } from "vitest";
import { ADMIN_FEATURE_LINKS, visibleAdminLinks } from "./adminFeatures";

const keys = (links) => links.map((l) => l.key).sort();

describe("admin hub tiles (F-97)", () => {
  it("shows the main admin every tile", () => {
    expect(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isAdmin: true, can: () => true })).toHaveLength(
      ADMIN_FEATURE_LINKS.length
    );
  });

  it("shows a deputy the owner tiles they were given, never the owner-only ones", () => {
    const shown = keys(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isSecondaryAdmin: true, can: () => true }));
    expect(shown).not.toContain("users");
    for (const tile of ["roles", "settings", "api-management", "vault", "backups", "geolock", "audit-report", "ads"]) {
      expect(shown).toContain(tile);
    }
    const backupsOnly = (key) => key === "manage_backups";
    expect(keys(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isSecondaryAdmin: true, can: backupsOnly }))).toEqual(["backups"]);
  });

  it("follows the sub-admin's toggles", () => {
    const can = (key) => key === "handle_reports";
    expect(keys(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isSecondaryAdmin: true, can }))).toEqual(["chapter-reports"]);
  });

  it("shows readers nothing", () => {
    expect(visibleAdminLinks(ADMIN_FEATURE_LINKS, { can: () => true })).toEqual([]);
  });
});
