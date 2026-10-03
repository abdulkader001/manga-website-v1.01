export const ADMIN_FEATURE_LINKS = [
  {
    key: "series",
    label: "Series Management",
    to: "/admin/series",
    description:
      "Scrape new manga, rescrape chapters, and configure automatic scraper schedule.",
    minRole: "secondary",
    permission: "edit_series",
  },
  {
    key: "roles",
    label: "Role Management",
    to: "/admin/roles",
    description: "Calibrate sub-admin power levels, promote, demote, and assign duties.",
    minRole: "secondary",
    permission: "manage_roles",
  },
  {
    key: "users",
    label: "User Database",
    to: "/admin/users",
    description: "Search the full user directory, handle badges, and inspect accounts.",
    minRole: "secondary",
    permission: "view_user_list",
  },
  {
    key: "ads",
    label: "Ads & Placements Manager",
    to: "/admin/ads",
    description: "Create ad slots, configure banner creatives, and manage page placements.",
    minRole: "secondary",
    permission: "manage_ads",
  },
  {
    key: "health",
    label: "System Health",
    to: "/admin/health",
    description: "Check service telemetry, uptime, background jobs, and diagnostic signals.",
    minRole: "secondary",
    permission: "view_system_health",
  },
  {
    key: "audit-report",
    label: "Operations & Traffic Audit",
    to: "/admin/audit-report",
    description: "24-hr UTC cycle audit, concurrent watchers per manga, uptime, and daily logins.",
    minRole: "secondary",
    permission: "view_system_health",
  },
  {
    key: "chapter-reports",
    label: "Chapter Reports & Single Re-scrape",
    to: "/admin/chapter-reports",
    description: "Inspect reader error reports and re-scrape single chapters cleanly.",
    minRole: "secondary",
    permission: "handle_reports",
  },
  {
    key: "api-management",
    label: "API Management",
    to: "/admin/api-management",
    description: "Manage OCR, AI, and Translation engines, custom endpoints, and API keys.",
    minRole: "secondary",
    permission: "view_providers",
  },
  {
    key: "settings",
    label: "Admin Settings",
    to: "/admin/settings",
    description: "Edit site branding, default reader settings, maintenance, footer, and navigation.",
    minRole: "secondary",
    permission: "manage_admin_settings",
  },
  {
    key: "vault",
    label: "Secret Vault",
    to: "/admin/vault",
    description:
      "Google/Microsoft sign-in, SMTP and API keys, encrypted. A site-owner power.",
    minRole: "secondary",
    permission: "manage_secret_vault",
  },
  {
    key: "backups",
    label: "Storage & Backups",
    to: "/admin/backups",
    description:
      "Weekly whole-site backups: download, upload, restore, and copy to R2 / B2 / MinIO storage. A site-owner power.",
    minRole: "secondary",
    permission: "manage_backups",
  },
  {
    key: "geolock",
    label: "Geolock",
    to: "/admin/geolock",
    description: "Choose countries that can't open the site. A site-owner power.",
    minRole: "secondary",
    permission: "manage_geolock",
  },
  {
    key: "functions",
    label: "Site Functions",
    to: "/admin/functions",
    description:
      "Switch each website function on or off: sign-in methods, comments, ads, translation, scraping and more. Owner only.",
    // Never delegable: there is no permission for it, so only the owner sees it.
    minRole: "owner",
    permission: null,
  },
];

/**
 * Admin hub tiles a person may see. The owner sees them all. Everyone else sees
 * the tiles whose permission they hold ("secondary" tiles), exactly the rule
 * their routes apply (AuthGuard `permission`). Tiles marked minRole "owner" open
 * owner-only pages (Site Functions) and are never shown to anyone else. A person
 * whose powers the owner switched off sees none.
 */
export function visibleAdminLinks(links, { isAdmin, isSecondaryAdmin, can, suspended = false }) {
  if (isAdmin) return links;
  if (!isSecondaryAdmin || suspended) return [];
  return links.filter((link) => link.minRole === "secondary" && Boolean(link.permission) && can(link.permission));
}
