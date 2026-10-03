import { describe, it, expect, vi, beforeEach } from "vitest";

const apiFetch = vi.fn(() => Promise.resolve({ ok: true }));
vi.mock("../services/api", () => ({ apiFetch: (...a) => apiFetch(...a) }));

import { reportError, _resetErrorReporter } from "./errorReporter";

describe("browser error reporter", () => {
  beforeEach(() => {
    apiFetch.mockClear();
    _resetErrorReporter();
  });

  it("sends the error with the page path only", () => {
    window.history.pushState({}, "", "/manga/5?token=abc");
    expect(reportError(new TypeError("x is not a function"))).toBe(true);
    const [path, init] = apiFetch.mock.calls[0];
    expect(path).toBe("/errors/report");
    const body = JSON.parse(init.body);
    expect(body).toMatchObject({ kind: "TypeError", message: "x is not a function", page: "/manga/5" });
  });

  it("sends the same error once and caps a flood", () => {
    reportError(new Error("same"));
    reportError(new Error("same"));
    expect(apiFetch).toHaveBeenCalledTimes(1);
    for (let i = 0; i < 30; i += 1) reportError(new Error(`e${i}`));
    expect(apiFetch).toHaveBeenCalledTimes(10);
  });
});
