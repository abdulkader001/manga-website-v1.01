import React from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderAt } from "../../test/render";

const registry = vi.hoisted(() => ({
  get: vi.fn(),
  saveProvider: vi.fn(),
  deleteProvider: vi.fn(),
  testConnection: vi.fn(),
}));
vi.mock("../../services/api", () => ({ default: { admin: { apiRegistry: registry } } }));

import ApiManagement from "./ApiManagement";

const provider = { id: "deepl_custom", label: "DeepL Custom", apiKey: "", defaultUrl: "", enabled: true, isCustom: true };
const refusal = () => {
  throw new Error("A fresh authenticator code is required.");
};

describe("API Management shows what the server did (plan.md P1-10)", () => {
  beforeEach(() => {
    Object.values(registry).forEach((fn) => fn.mockReset());
    registry.get.mockResolvedValue({ ocr: [], ai: [], translation: [provider] });
  });

  it("says a refused save was not saved, and keeps the form open", async () => {
    registry.saveProvider.mockImplementation(async () => refusal());
    const user = userEvent.setup();
    renderAt(<ApiManagement />);
    await screen.findByText("DeepL Custom");
    await user.click(screen.getByRole("button", { name: /Add New API Provider/ }));
    await user.type(screen.getByPlaceholderText(/DeepL Pro Engine/), "My OCR");
    await user.click(screen.getByRole("button", { name: /Save Provider/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("My OCR was not saved: A fresh authenticator code is required.");
    expect(screen.queryByText(/saved locally/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save Provider/ })).toBeInTheDocument();
  });

  it("keeps a provider the server refused to delete", async () => {
    registry.deleteProvider.mockImplementation(async () => refusal());
    const user = userEvent.setup();
    renderAt(<ApiManagement />);
    await screen.findByText("DeepL Custom");
    await user.click(screen.getByTitle("Delete Provider"));
    expect(await screen.findByText(/DeepL Custom was not deleted/)).toBeInTheDocument();
    expect(screen.getByText("DeepL Custom")).toBeInTheDocument();
  });

  it("reports a failed connection test as failed", async () => {
    registry.testConnection.mockImplementation(async () => {
      throw new Error("401 Unauthorized");
    });
    const user = userEvent.setup();
    renderAt(<ApiManagement />);
    await screen.findByText("DeepL Custom");
    await user.click(screen.getByRole("button", { name: /Test Connection/ }));
    expect(await screen.findByText(/Connection failed: 401 Unauthorized/)).toBeInTheDocument();
  });

  it("no longer keeps a copy of the providers in the browser", async () => {
    localStorage.setItem("manga_admin_api_registry_v1", JSON.stringify({ ocr: [{ id: "x", apiKey: "secret" }] }));
    renderAt(<ApiManagement />);
    await screen.findByText("DeepL Custom");
    expect(localStorage.getItem("manga_admin_api_registry_v1")).toBeNull();
  });
});
