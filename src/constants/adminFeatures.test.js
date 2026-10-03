import { describe, expect, it } from "vitest";
import { ADMIN_FEATURE_LINKS, visibleAdminLinks } from "./adminFeatures";

const keys = (links) => links.map((l) => l.key).sort();

describe("admin hub tiles (F-97)", () => {
  it("shows the main admin every tile", () => {
    expect(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isAdmin: true, can: () => true })).toHaveLength(
      ADMIN_FEATURE_LINKS.length
    );
  });

  it("shows an Admin the tiles their toggles allow, never the owner-only Site Functions", () => {
    const shown = keys(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isSecondaryAdmin: true, can: () => true }));
    expect(shown).not.toContain("functions");
    for (const tile of ["users", "roles", "settings", "api-management", "vault", "backups", "geolock", "audit-report", "ads"]) {
      expect(shown).toContain(tile);
    }
    const backupsOnly = (key) => key === "manage_backups";
    expect(keys(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isSecondaryAdmin: true, can: backupsOnly }))).toEqual(["backups"]);
  });

  it("follows the sub-admin's toggles", () => {
    const can = (key) => key === "handle_reports";
    expect(keys(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isSecondaryAdmin: true, can }))).toEqual(["chapter-reports"]);
  });

  it("keeps Site Functions for the owner alone, whatever anyone holds", () => {
    expect(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isAdmin: true, can: () => true }).map((l) => l.key)).toContain("functions");
    expect(keys(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isSecondaryAdmin: true, can: () => true }))).not.toContain("functions");
    const fn = ADMIN_FEATURE_LINKS.find((l) => l.key === "functions");
    expect(fn.permission).toBeNull();
    expect(fn.minRole).toBe("owner");
  });

  it("shows a person whose powers the owner switched off nothing at all", () => {
    expect(visibleAdminLinks(ADMIN_FEATURE_LINKS, { isSecondaryAdmin: true, can: () => true, suspended: true })).toEqual([]);
  });

  it("shows readers nothing", () => {
    expect(visibleAdminLinks(ADMIN_FEATURE_LINKS, { can: () => true })).toEqual([]);
  });
});
