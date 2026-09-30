export const ADMIN_FEATURE_LINKS = [
  {
    key: "series",
    label: "Series Management",
    to: "/admin/series",
    description:
      "Scrape new manga, rescrape chapters, and configure automatic scraper schedule.",
    minRole: "secondary",
  },
  {
    key: "roles",
    label: "Role Management",
    to: "/admin/roles",
    description: "Calibrate sub-admin power levels, promote, demote, and assign duties.",
    minRole: "admin",
  },
  {
    key: "users",
    label: "User Database",
    to: "/admin/users",
    description: "Search the full user directory, handle badges, and inspect accounts.",
    minRole: "admin",
  },
  {
    key: "ads",
    label: "Ads & Placements Manager",
    to: "/admin/ads",
    description: "Create ad slots, configure banner creatives, and manage page placements.",
    minRole: "admin",
  },
  {
    key: "health",
    label: "System Health",
    to: "/admin/health",
    description: "Check service telemetry, uptime, background jobs, and diagnostic signals.",
    minRole: "secondary",
  },
  {
    key: "audit-report",
    label: "Operations & Traffic Audit",
    to: "/admin/audit-report",
    description: "24-hr BST cycle audit, concurrent watchers per manga, uptime, and daily logins.",
    minRole: "admin",
  },
  {
    key: "chapter-reports",
    label: "Chapter Reports & Single Re-scrape",
    to: "/admin/chapter-reports",
    description: "Inspect reader error reports and re-scrape single chapters cleanly.",
    minRole: "secondary",
  },
  {
    key: "api-management",
    label: "API Management",
    to: "/admin/api-management",
    description: "Manage OCR, AI, and Translation engines, custom endpoints, and API keys.",
    minRole: "admin",
  },
  {
    key: "settings",
    label: "Admin Settings",
    to: "/admin/settings",
    description: "Edit site branding, default reader settings, maintenance, footer, and navigation.",
    minRole: "admin",
  },
];

export const ADMIN_NAV_LINKS = ADMIN_FEATURE_LINKS.map((item) => ({ ...item }));
