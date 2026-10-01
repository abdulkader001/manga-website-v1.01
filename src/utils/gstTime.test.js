import { describe, it, expect } from "vitest";
import { formatTimeAgo } from "./gstTime";

const hoursAgo = (h) => new Date(Date.now() - h * 3600e3).toISOString();

describe("formatTimeAgo", () => {
  it("reads the server's UTC times correctly in every format", () => {
    const iso = hoursAgo(3);
    expect(formatTimeAgo(iso)).toBe("3h ago");
    expect(formatTimeAgo(iso.replace("Z", ""))).toBe("3h ago"); // naive UTC
    expect(formatTimeAgo(iso.replace("Z", "+00:00"))).toBe("3h ago");
  });

  it("never says 'Just now' for a missing or broken time", () => {
    expect(formatTimeAgo(null)).toBe("");
    expect(formatTimeAgo("not a date")).toBe("");
    expect(formatTimeAgo(hoursAgo(-5))).toBe("");
  });

  it("says 'Just now' only for the last few seconds", () => {
    expect(formatTimeAgo(new Date().toISOString())).toBe("Just now");
    expect(formatTimeAgo(hoursAgo(2 / 60))).toBe("2m ago");
  });
});
