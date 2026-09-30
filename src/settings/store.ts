import { useState, useEffect } from "react";
import type { ProviderKind, ProviderMetadata } from "../plugins/types";

export type LimitPeriod = "day" | "week" | "month" | "daily" | "weekly" | "monthly" | "none";

export interface ProviderConfig {
  id: string;
  apiKey?: string;
  apiUrl?: string;
  model?: string;
  [key: string]: any;
}

export interface SettingsState {
  targetLanguage: string;
  ocr: ProviderConfig;
  translation: ProviderConfig;
  ai: ProviderConfig;
  translationLimit: {
    amount: number | null;
    period: LimitPeriod;
  };
  [key: string]: any;
}

const defaultState: SettingsState = {
  targetLanguage: "en",
  ocr: {
    id: "tesseract",
    apiKey: "",
    apiUrl: "",
    model: "",
  },
  translation: {
    id: "google_translate",
    apiKey: "",
    apiUrl: "",
    model: "",
  },
  ai: {
    id: "gemini",
    apiKey: "",
    apiUrl: "",
    model: "gemini-2.5-flash",
  },
  translationLimit: {
    amount: null,
    period: "day",
  },
};

let currentStore: SettingsState = (() => {
  try {
    const saved = localStorage.getItem("mgeko_settings");
    if (saved) {
      return { ...defaultState, ...JSON.parse(saved) };
    }
  } catch (e) {
    // Ignore storage parse errors
  }
  return { ...defaultState };
})();

const listeners = new Set<() => void>();

function notify() {
  try {
    localStorage.setItem("mgeko_settings", JSON.stringify(currentStore));
  } catch (e) {
    // Ignore
  }
  listeners.forEach((l) => l());
}

export function useSettingsStore<T = SettingsState>(selector?: (state: SettingsState) => T): T {
  const [, setTick] = useState(0);

  useEffect(() => {
    const listener = () => setTick((t) => t + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);

  if (selector) {
    return selector(currentStore);
  }
  return currentStore as unknown as T;
}

export function setTargetLanguage(lang: string) {
  currentStore = { ...currentStore, targetLanguage: lang };
  notify();
}

export function setProvider(kind: string, selectionOrId: any) {
  const nextConfig: ProviderConfig =
    typeof selectionOrId === "string"
      ? { ...(currentStore[kind] || {}), id: selectionOrId }
      : { ...(currentStore[kind] || {}), ...(selectionOrId || {}) };

  currentStore = {
    ...currentStore,
    [kind]: nextConfig,
  };
  notify();
}

export function updateProvider(kind: string, updates: Partial<ProviderConfig>, extra?: any) {
  const current = currentStore[kind] || { id: "default" };
  currentStore = {
    ...currentStore,
    [kind]: {
      ...current,
      ...updates,
      ...(extra || {}),
    },
  };
  notify();
}

export function resetProvider(kind: string, extra?: any) {
  const baseDefault = (defaultState as any)[kind] || { id: "default" };
  currentStore = {
    ...currentStore,
    [kind]: { ...baseDefault },
  };
  notify();
}

export function updateTranslationLimit(updates: Partial<SettingsState["translationLimit"]>) {
  currentStore = {
    ...currentStore,
    translationLimit: {
      ...currentStore.translationLimit,
      ...updates,
    },
  };
  notify();
}

export function getProviderOptions(kind: ProviderKind | string): ProviderMetadata[] {
  if (kind === "ocr") {
    return [
      {
        id: "tesseract",
        name: "Tesseract WebAssembly (Local)",
        label: "Tesseract WebAssembly (Local)",
        description: "Runs entirely inside the client browser without external API costs.",
        requiresKey: false,
        allowsUrl: false,
        allowsModel: false,
      },
      {
        id: "google_vision",
        name: "Google Cloud Vision API",
        label: "Google Cloud Vision API",
        description: "Cloud-based OCR with high Japanese kana & kanji accuracy.",
        requiresKey: true,
        allowsUrl: true,
        allowsModel: false,
      },
    ];
  }

  if (kind === "translation") {
    return [
      {
        id: "google_translate",
        name: "Google Cloud Translation",
        label: "Google Cloud Translation",
        description: "Fast cloud neural machine translation for comic dialogues.",
        requiresKey: true,
        allowsUrl: true,
        allowsModel: false,
      },
      {
        id: "deepl",
        name: "DeepL Translate API",
        label: "DeepL Translate API",
        description: "Nuanced contextual translations for manga expressions.",
        requiresKey: true,
        allowsUrl: true,
        allowsModel: false,
      },
      {
        id: "my_memory",
        name: "MyMemory API (Free Tier)",
        label: "MyMemory API (Free Tier)",
        description: "Collaborative translation memory service with daily quota.",
        requiresKey: false,
        allowsUrl: false,
        allowsModel: false,
      },
    ];
  }

  if (kind === "ai") {
    return [
      {
        id: "gemini",
        name: "Google Gemini 2.5 Flash",
        label: "Google Gemini 2.5 Flash",
        description: "High-speed multimodal AI for OCR reasoning & localized translations.",
        requiresKey: true,
        allowsUrl: true,
        allowsModel: true,
        defaultModel: "gemini-2.5-flash",
      },
      {
        id: "openai",
        name: "OpenAI GPT-4o-mini",
        label: "OpenAI GPT-4o-mini",
        description: "Compact multimodal model for manga dialog localization.",
        requiresKey: true,
        allowsUrl: true,
        allowsModel: true,
        defaultModel: "gpt-4o-mini",
      },
    ];
  }

  return [];
}

export function maskSecret(secret?: string) {
  if (!secret) return "";
  if (secret.length <= 4) return "••••";
  return secret.slice(0, 2) + "••••••••" + secret.slice(-2);
}
