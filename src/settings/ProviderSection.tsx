import React, { useEffect, useState } from "react";
import { apiFetch } from "../services/api";

// One reader-owned provider (OCR / translation / AI), stored server-side and
// encrypted (POST /integrations/add). The reader pipeline reads exactly this
// record, so what is saved here is what translates the pages.

export type ServiceKind = "ai" | "ocr" | "translation";

export type SavedIntegration = {
  provider?: string;
  apiKey?: string | null; // masked by the server
  apiUrl?: string | null;
  model?: string | null;
};

type Option = { id: string; label: string; needsKey: boolean; urlHint?: string; modelHint?: string };

const OPTIONS: Record<ServiceKind, Option[]> = {
  ai: [
    {
      id: "google_gemini",
      label: "Google Gemini (free tier available)",
      needsKey: true,
      urlHint: "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
    },
    {
      id: "openai_gpt_3_5",
      label: "OpenAI / any OpenAI-compatible API",
      needsKey: true,
      urlHint: "https://api.openai.com/v1/chat/completions",
      modelHint: "gpt-4o-mini",
    },
    { id: "deepseek_chat", label: "DeepSeek", needsKey: true, modelHint: "deepseek-chat" },
    { id: "openrouter_free", label: "OpenRouter", needsKey: true, modelHint: "meta-llama/llama-3.1-8b-instruct:free" },
    { id: "qwen_plus", label: "Qwen (DashScope)", needsKey: true, modelHint: "qwen-plus" },
    { id: "custom", label: "Custom chat-completions endpoint", needsKey: true, urlHint: "https://…/v1/chat/completions" },
  ],
  ocr: [
    { id: "tesseract_local", label: "Built-in Tesseract (free, runs on our server)", needsKey: false },
    { id: "ocr_space_free", label: "OCR.space", needsKey: true },
    { id: "google_cloud_vision", label: "Google Cloud Vision", needsKey: true },
    { id: "azure_computer_vision", label: "Azure Computer Vision", needsKey: true },
    { id: "custom", label: "Custom OCR endpoint", needsKey: true, urlHint: "https://…" },
  ],
  translation: [
    { id: "google_cloud_translate", label: "Google Cloud Translation", needsKey: true },
    { id: "azure_translator", label: "Azure Translator", needsKey: true },
    { id: "libretranslate_demo", label: "LibreTranslate", needsKey: true, urlHint: "https://libretranslate.com/translate" },
    { id: "custom", label: "Custom translation endpoint", needsKey: true, urlHint: "https://…" },
  ],
};

const META: Record<ServiceKind, { icon: string; color: string; border: string; bg: string }> = {
  ai: { icon: "fas fa-brain", color: "text-purple-400", border: "border-purple-500/30", bg: "bg-purple-500/10" },
  ocr: { icon: "fas fa-eye", color: "text-[#00AEF0]", border: "border-[#00AEF0]/30", bg: "bg-[#00AEF0]/10" },
  translation: { icon: "fas fa-language", color: "text-emerald-400", border: "border-emerald-500/30", bg: "bg-emerald-500/10" },
};

const FIELD =
  "w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono";

/**
 * Accept a pasted `curl …` command (what provider docs show) and pull out the
 * endpoint and key, so readers don't have to dissect it themselves.
 */
export function parseCurl(raw: string): { url?: string; key?: string } {
  const text = raw.trim();
  if (!/^curl\s/i.test(text)) return {};
  const urlMatch = text.match(/https?:\/\/[^\s"'\\]+/);
  let key: string | undefined;
  const header = text.match(/(?:x-goog-api-key|api-key|x-api-key)\s*:\s*([^"'\s]+)/i);
  const bearer = text.match(/authorization\s*:\s*bearer\s+([^"'\s]+)/i);
  if (header) key = header[1];
  else if (bearer) key = bearer[1];
  let url = urlMatch?.[0];
  if (url) {
    try {
      const parsed = new URL(url);
      const queryKey = parsed.searchParams.get("key");
      if (queryKey) {
        key = key || queryKey;
        parsed.searchParams.delete("key");
      }
      url = parsed.toString();
    } catch {
      // keep the raw match
    }
  }
  // Placeholders such as $GEMINI_API_KEY are not keys.
  if (key && key.startsWith("$")) key = undefined;
  return { url, key };
}

async function readJson(res: Response) {
  try {
    return await res.json();
  } catch {
    return null;
  }
}

export default function ProviderSection({
  kind,
  title,
  subtitle,
  saved,
  onSaved,
}: {
  kind: ServiceKind;
  title: string;
  subtitle: string;
  saved: SavedIntegration | null;
  onSaved: (kind: ServiceKind, value: SavedIntegration | null) => void;
}) {
  const options = OPTIONS[kind];
  const isSaved = Boolean(saved && saved.provider && saved.provider !== "system");
  const [provider, setProvider] = useState(saved?.provider || options[0].id);
  const [apiKey, setApiKey] = useState("");
  const [apiUrl, setApiUrl] = useState(saved?.apiUrl || "");
  const [model, setModel] = useState(saved?.model || "");
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState<"" | "save" | "remove" | "test">("");
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  useEffect(() => {
    setProvider(saved?.provider && saved.provider !== "system" ? saved.provider : options[0].id);
    setApiUrl(saved?.apiUrl || "");
    setModel(saved?.model || "");
    setApiKey("");
  }, [saved, options]);

  const option = options.find((o) => o.id === provider) || options[0];
  const meta = META[kind];

  const onUrlChange = (value: string) => {
    const curl = parseCurl(value);
    if (curl.url) {
      setApiUrl(curl.url);
      if (curl.key) setApiKey(curl.key);
      if (kind === "ai" && /generativelanguage\.googleapis\.com/.test(curl.url)) setProvider("google_gemini");
      setResult({
        ok: true,
        message: curl.key
          ? "Read the endpoint and key from your curl command. Press Save."
          : "Read the endpoint from your curl command. Paste your API key, then press Save.",
      });
      return;
    }
    setApiUrl(value);
    setResult(null);
  };

  const save = async () => {
    setBusy("save");
    setResult(null);
    try {
      const res = await apiFetch("/api/v1/integrations/add", {
        method: "POST",
        body: JSON.stringify({
          service: kind,
          config: {
            provider,
            apiKey: apiKey.trim() || undefined,
            apiUrl: apiUrl.trim() || undefined,
            model: model.trim() || undefined,
          },
        }),
      });
      const data = await readJson(res);
      if (!res.ok) throw new Error(data?.error?.message || data?.detail || `Save failed (HTTP ${res.status})`);
      onSaved(kind, data.integration);
      setApiKey("");
      setResult({ ok: true, message: "Saved to your account. Press Test to check it works." });
    } catch (err: any) {
      setResult({ ok: false, message: err?.message || "Save failed." });
    } finally {
      setBusy("");
    }
  };

  const remove = async () => {
    if (!window.confirm("Remove this provider? Pages will use the site's built-in engines again.")) return;
    setBusy("remove");
    setResult(null);
    try {
      const res = await apiFetch("/api/v1/integrations/remove", {
        method: "DELETE",
        body: JSON.stringify({ service: kind }),
      });
      if (!res.ok) throw new Error(`Remove failed (HTTP ${res.status})`);
      onSaved(kind, null);
      setResult({ ok: true, message: "Removed." });
    } catch (err: any) {
      setResult({ ok: false, message: err?.message || "Remove failed." });
    } finally {
      setBusy("");
    }
  };

  const test = async () => {
    setBusy("test");
    setResult(null);
    try {
      const res = await apiFetch("/api/v1/integrations/test", {
        method: "POST",
        body: JSON.stringify({ service: kind }),
      });
      const data = await readJson(res);
      const message = data?.message || data?.error?.message || `HTTP ${res.status}`;
      setResult({
        ok: Boolean(res.ok && data?.success),
        message: data?.latencyMs ? `${message} (${data.latencyMs} ms)` : message,
      });
    } catch (err: any) {
      setResult({ ok: false, message: "Connection error: " + (err?.message || "unknown") });
    } finally {
      setBusy("");
    }
  };

  return (
    <section className={`bg-[#15171c] border ${meta.border} rounded-2xl p-5 shadow-xl space-y-4 text-xs`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className={`w-9 h-9 rounded-xl ${meta.bg} flex items-center justify-center ${meta.color} text-sm flex-shrink-0`}>
            <i className={meta.icon}></i>
          </div>
          <div>
            <h3 className="text-sm font-bold text-white">{title}</h3>
            <p className="text-[11px] text-[#8b93a3] mt-0.5">{subtitle}</p>
          </div>
        </div>
        <span
          className={`shrink-0 px-2 py-0.5 rounded-lg text-[10px] font-bold border ${
            isSaved
              ? "bg-emerald-500/10 text-emerald-300 border-emerald-500/30"
              : "bg-[#262a33] text-[#8b93a3] border-[#262a33]"
          }`}
        >
          {isSaved ? "Saved" : "Using site default"}
        </span>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="sm:col-span-2">
          <label className="font-semibold text-gray-300 block mb-1">Provider</label>
          <select
            value={provider}
            onChange={(e) => {
              setProvider(e.target.value);
              setResult(null);
            }}
            className={FIELD}
          >
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        </div>

        {option.needsKey && (
          <div>
            <label className="font-semibold text-gray-300 block mb-1">API key</label>
            <div className="relative">
              <input
                type={showKey ? "text" : "password"}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={isSaved && saved?.apiKey ? `Saved: ${saved.apiKey} (leave empty to keep)` : "Paste your API key"}
                autoComplete="off"
                className={`${FIELD} pr-9`}
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2.5 top-2 text-gray-400 hover:text-white"
                aria-label={showKey ? "Hide key" : "Show key"}
              >
                <i className={showKey ? "fas fa-eye-slash" : "fas fa-eye"}></i>
              </button>
            </div>
          </div>
        )}

        {provider !== "tesseract_local" && (
          <div>
            <label className="font-semibold text-gray-300 block mb-1">Endpoint URL (optional)</label>
            <input
              type="text"
              value={apiUrl}
              onChange={(e) => onUrlChange(e.target.value)}
              placeholder={option.urlHint || "Default endpoint, or paste a curl command"}
              className={FIELD}
            />
          </div>
        )}

        {kind === "ai" && provider !== "google_gemini" && (
          <div>
            <label className="font-semibold text-gray-300 block mb-1">Model</label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder={option.modelHint || "model name"}
              className={FIELD}
            />
          </div>
        )}
      </div>

      {result && (
        <div
          className={`p-3 rounded-xl border text-xs ${
            result.ok ? "bg-emerald-950/40 border-emerald-800 text-emerald-300" : "bg-red-950/40 border-red-800 text-red-300"
          }`}
        >
          {result.message}
        </div>
      )}

      <div className="flex flex-wrap justify-end gap-2 pt-1">
        {isSaved && (
          <button
            type="button"
            disabled={Boolean(busy)}
            onClick={remove}
            className="px-4 py-1.5 rounded-xl border border-red-500/40 text-red-300 hover:bg-red-500/10 text-xs font-semibold transition disabled:opacity-50"
          >
            {busy === "remove" ? "Removing…" : "Remove"}
          </button>
        )}
        <button
          type="button"
          disabled={Boolean(busy) || !isSaved}
          onClick={test}
          title={isSaved ? "" : "Save first"}
          className="px-4 py-1.5 rounded-xl bg-[#101216] hover:bg-[#1f2330] border border-[#262a33] text-gray-300 hover:text-white text-xs font-semibold transition flex items-center gap-1.5 disabled:opacity-50"
        >
          <i className={busy === "test" ? "fas fa-spinner fa-spin" : "fas fa-vial"}></i>
          <span>{busy === "test" ? "Testing…" : "Test connection"}</span>
        </button>
        <button
          type="button"
          disabled={Boolean(busy) || (option.needsKey && !apiKey.trim() && !(isSaved && saved?.provider === provider))}
          onClick={save}
          className="px-4 py-1.5 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white text-xs font-bold transition flex items-center gap-1.5 disabled:opacity-50"
        >
          <i className={busy === "save" ? "fas fa-spinner fa-spin" : "fas fa-save"}></i>
          <span>{busy === "save" ? "Saving…" : "Save"}</span>
        </button>
      </div>
    </section>
  );
}
