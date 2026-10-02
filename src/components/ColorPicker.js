import React, { useEffect, useRef, useState } from "react";
import { hexToHsv, hsvToHex } from "../utils/color";

// Colour picker: a square to pick how light/dark and how strong the colour
// is (left = white/grey, right = full colour, bottom = black), and a rainbow
// bar under it to pick the colour itself. Arrow keys move either pointer.

const clamp01 = (n) => Math.min(1, Math.max(0, n));

function useDrag(onMove) {
  const ref = useRef(null);
  const handle = (e) => {
    const rect = ref.current.getBoundingClientRect();
    onMove(clamp01((e.clientX - rect.left) / rect.width), clamp01((e.clientY - rect.top) / rect.height));
  };
  const onPointerDown = (e) => {
    e.preventDefault();
    e.currentTarget.setPointerCapture?.(e.pointerId);
    handle(e);
  };
  const onPointerMove = (e) => {
    if (e.buttons & 1) handle(e);
  };
  return { ref, onPointerDown, onPointerMove };
}

export default function ColorPicker({ value, onChange, label = "Colour" }) {
  const [hsv, setHsv] = useState(() => hexToHsv(value) || { h: 0, s: 0, v: 1 });
  const [text, setText] = useState(value || "");

  // Follow outside changes (reset, automatic) without fighting the user's hue
  // while they drag through greys, where the hue can't be read back.
  useEffect(() => {
    setText(value || "");
    const next = hexToHsv(value);
    if (next && hsvToHex(hsv.h, hsv.s, hsv.v) !== (value || "").toLowerCase()) {
      setHsv((cur) => (next.s === 0 || next.v === 0 ? { ...next, h: cur.h } : next));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const commit = (next) => {
    setHsv(next);
    const hex = hsvToHex(next.h, next.s, next.v);
    setText(hex);
    onChange(hex);
  };

  const square = useDrag((x, y) => commit({ ...hsv, s: x, v: 1 - y }));
  const hue = useDrag((x) => commit({ ...hsv, h: x * 360 }));
  const pure = hsvToHex(hsv.h, 1, 1);
  const current = hsvToHex(hsv.h, hsv.s, hsv.v);

  const squareKeys = (e) => {
    const d = e.shiftKey ? 0.1 : 0.02;
    const moves = { ArrowLeft: [-d, 0], ArrowRight: [d, 0], ArrowUp: [0, d], ArrowDown: [0, -d] };
    const m = moves[e.key];
    if (!m) return;
    e.preventDefault();
    commit({ ...hsv, s: clamp01(hsv.s + m[0]), v: clamp01(hsv.v + m[1]) });
  };
  const hueKeys = (e) => {
    const d = e.shiftKey ? 30 : 5;
    const m = { ArrowLeft: -d, ArrowDown: -d, ArrowRight: d, ArrowUp: d }[e.key];
    if (!m) return;
    e.preventDefault();
    commit({ ...hsv, h: (hsv.h + m + 360) % 360 });
  };

  return (
    <div className="space-y-2 select-none" data-testid="color-picker">
      <div
        {...square}
        role="slider"
        tabIndex={0}
        aria-label={`${label}: lightness and strength`}
        aria-valuetext={current}
        onKeyDown={squareKeys}
        className="relative h-32 w-full rounded-lg cursor-crosshair touch-none border border-[#262a33]"
        style={{
          background: `linear-gradient(to top, #000, transparent), linear-gradient(to right, #fff, ${pure})`,
        }}
      >
        <span
          className="absolute w-4 h-4 -ml-2 -mt-2 rounded-full border-2 border-white shadow-[0_0_0_1px_rgba(0,0,0,0.6)] pointer-events-none"
          style={{ left: `${hsv.s * 100}%`, top: `${(1 - hsv.v) * 100}%`, background: current }}
        />
      </div>
      <div
        {...hue}
        role="slider"
        tabIndex={0}
        aria-label={`${label}: colour`}
        aria-valuemin={0}
        aria-valuemax={360}
        aria-valuenow={Math.round(hsv.h)}
        onKeyDown={hueKeys}
        className="relative h-4 w-full rounded-full cursor-pointer touch-none border border-[#262a33]"
        style={{
          background: "linear-gradient(to right, #f00, #ff0, #0f0, #0ff, #00f, #f0f, #f00)",
        }}
      >
        <span
          className="absolute top-1/2 w-4 h-4 -ml-2 -mt-2 rounded-full border-2 border-white shadow-[0_0_0_1px_rgba(0,0,0,0.6)] pointer-events-none"
          style={{ left: `${(hsv.h / 360) * 100}%`, background: pure }}
        />
      </div>
      <div className="flex items-center gap-2">
        <span className="w-6 h-6 rounded-md border border-[#262a33]" style={{ background: current }} />
        <input
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            const next = hexToHsv(e.target.value);
            if (next) {
              setHsv(next);
              onChange(hsvToHex(next.h, next.s, next.v));
            }
          }}
          aria-label={`${label} code`}
          maxLength={7}
          placeholder="#rrggbb"
          className="w-24 px-2 py-1 rounded-lg bg-[#101216] border border-[#262a33] font-mono text-[11px] text-white focus:outline-none focus:border-[#00AEF0]"
        />
        {["#000000", "#ffffff"].map((swatch) => (
          <button
            key={swatch}
            type="button"
            onClick={() => commit(hexToHsv(swatch))}
            aria-label={swatch === "#000000" ? "Black" : "White"}
            className="w-6 h-6 rounded-md border border-[#3a3f4b]"
            style={{ background: swatch }}
          />
        ))}
      </div>
    </div>
  );
}
