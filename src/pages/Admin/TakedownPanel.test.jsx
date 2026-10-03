import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../../test/render";

const takedown = vi.fn();
vi.mock("../../services/api", () => ({
  default: { admin: { series: { takedown: (...a) => takedown(...a) } } },
}));

import TakedownPanel from "./TakedownPanel";

const manga = { id: 7, title: "Solo Story", takedown_status: "none" };

describe("Takedown panel (plan.md P1-2)", () => {
  beforeEach(() => {
    takedown.mockReset();
  });

  it("asks for the series name before taking it down", async () => {
    takedown.mockResolvedValue({ takedown_status: "taken_down" });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderAt(<TakedownPanel manga={manga} onClose={() => {}} onSaved={onSaved} />);

    await user.selectOptions(screen.getByLabelText("Status"), "taken_down");
    await user.type(screen.getByLabelText(/Reason/), "DMCA notice");
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();

    await user.type(screen.getByLabelText("Type the series name to confirm"), "Solo Story");
    await user.click(save);
    await waitFor(() =>
      expect(takedown).toHaveBeenCalledWith(7, { status: "taken_down", reason: "DMCA notice" })
    );
    expect(onSaved).toHaveBeenCalled();
  });

  it("shows the server's refusal and does not report success", async () => {
    takedown.mockImplementation(async () => {
      throw new Error("A fresh authenticator code is required.");
    });
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderAt(<TakedownPanel manga={manga} onClose={() => {}} onSaved={onSaved} />);

    await user.selectOptions(screen.getByLabelText("Status"), "requested");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("A fresh authenticator code is required.");
    expect(onSaved).not.toHaveBeenCalled();
  });
});
