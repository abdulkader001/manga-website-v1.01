import React from "react";
import { describe, it, expect } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import OverlayBox, { bubbleClipPath, outlineShadow } from "./OverlayBox";
import ColorPicker from "./ColorPicker";

const base = { overlay_style: "white_box", overlay_font: "standard_sans", overlay_font_size: 100 };

describe("bubble-shaped overlay", () => {
  it("clips the fill to the bubble's own shape", () => {
    expect(bubbleClipPath({ shape: "ellipse" })).toMatch(/^ellipse\(/);
    expect(bubbleClipPath({ shape: "rectangle" })).toMatch(/^inset\(/);
    const free = bubbleClipPath({ shape: "freeform", polygon: [[0, 0], [1, 0.2], [0.6, 1]] });
    expect(free).toMatch(/^polygon\(/);
    expect(free.split("calc(").length - 1).toBe(6);
    expect(bubbleClipPath(null)).toBeUndefined();
  });

  it("puts the text in the bubble's inner area at up to 70 px", () => {
    const { container } = render(
      <OverlayBox
        region={{ translated: "Hi", bubble: { shape: "ellipse", inner: { x: 0.15, y: 0.15, width: 0.7, height: 0.7 } } }}
        settings={base}
        style={{ left: 0, top: 0, width: 200, height: 100 }}
      />
    );
    const outer = container.firstChild;
    expect(outer.dataset.shape).toBe("ellipse");
    expect(outer.style.clipPath).toMatch(/ellipse/);
    const inner = outer.firstChild;
    expect(inner.style.left).toBe("15%");
    expect(inner.style.width).toBe("70%");
    expect(inner.style.fontSize).toBe("70px");
  });

  it("is a plain box when there is no bubble (text on the art)", () => {
    const { container } = render(<OverlayBox region={{ translated: "Boom" }} settings={base} style={{}} />);
    expect(container.firstChild.dataset.shape).toBe("box");
    expect(container.firstChild.style.clipPath).toBe("");
  });

  it("draws the outline in the reader's colour", () => {
    expect(outlineShadow({ overlay_outline_color: "#00ff88" }, { outline: false })).toContain("#00ff88");
    expect(outlineShadow({}, { outline: false })).toBeUndefined();
    expect(outlineShadow({}, { outline: true })).toContain("#000000");
  });
});

describe("colour picker", () => {
  it("moves through dark-to-bright and the rainbow with the keyboard", () => {
    const seen = [];
    render(<ColorPicker value="#ff0000" onChange={(v) => seen.push(v)} label="Text colour" />);
    const square = screen.getByRole("slider", { name: /lightness/ });
    fireEvent.keyDown(square, { key: "ArrowDown", shiftKey: true }); // darker
    expect(seen.at(-1)).toBe("#e60000");
    const hue = screen.getByRole("slider", { name: /Text colour: colour/ });
    fireEvent.keyDown(hue, { key: "ArrowRight", shiftKey: true }); // red -> orange-ish
    expect(seen.at(-1)).toBe("#e67300");
    fireEvent.click(screen.getByRole("button", { name: "White" }));
    expect(seen.at(-1)).toBe("#ffffff");
    fireEvent.change(screen.getByRole("textbox", { name: /code/ }), { target: { value: "#123456" } });
    expect(seen.at(-1)).toBe("#123456");
  });
});
