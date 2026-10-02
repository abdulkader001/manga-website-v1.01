import { describe, it, expect } from "vitest";
import { clampTextScale, textScaleToPx } from "./overlayText";
import { hexToHsv, hsvToHex } from "./color";

describe("translated text size", () => {
  it("runs 1-100 in half steps and tops out at 70 px", () => {
    expect(textScaleToPx(100)).toBe(70);
    expect(textScaleToPx(1)).toBe(0.7);
    expect(textScaleToPx(28.5)).toBe(19.95); // the old 20 px default
    expect(clampTextScale(0)).toBe(1);
    expect(clampTextScale(250)).toBe(100);
    expect(clampTextScale(42.26)).toBe(42.5);
    expect(clampTextScale("abc")).toBe(28.5);
  });
});

describe("colour conversion", () => {
  it("round-trips hex through hue/saturation/value", () => {
    for (const hex of ["#000000", "#ffffff", "#ff0000", "#00aef0", "#7f3fbf"]) {
      const { h, s, v } = hexToHsv(hex);
      expect(hsvToHex(h, s, v)).toBe(hex);
    }
    expect(hexToHsv("red")).toBeNull();
  });
});
