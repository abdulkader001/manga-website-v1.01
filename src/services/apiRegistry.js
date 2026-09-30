import { useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "manga_admin_api_registry_v1";

const RAW_DEFAULTS = {
  ocr: [
    {
      id: "system",
      label: "Use site default (managed)",
      description: "Let the site automatically select the best OCR integration for everyone.",
      requiresKey: false,
      allowsUrl: false,
      allowsModel: false,
      isVerified: true,
    },
    {
      id: "tesseract_local",
      label: "Tesseract.js (On-device OCR)",
      description: "Runs entirely in the browser using WebAssembly. No network calls or API keys required.",
      requiresKey: false,
      allowsUrl: false,
      allowsModel: false,
      isVerified: true,
    },
    {
      id: "ocr_space_free",
      label: "OCR.space (Free tier)",
      description: "Free OCR API with generous limits. Requires registering for an API key.",
      defaultUrl: "https://api.ocr.space/parse/image",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: false,
      isVerified: true,
    },
    {
      id: "google_cloud_vision",
      label: "Google Cloud Vision OCR",
      description: "Connect your Google Cloud project for production-grade OCR.",
      defaultUrl: "https://vision.googleapis.com/v1/images:annotate",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: false,
      isVerified: true,
    },
    {
      id: "azure_computer_vision",
      label: "Microsoft Azure Computer Vision",
      description: "Use Azure's OCR service with regional endpoints.",
      defaultUrl: "https://api.cognitive.microsoft.com/vision/v3.2/ocr",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      modelPlaceholder: "Azure region (e.g., eastus)",
      isVerified: true,
    },
    {
      id: "amazon_textract",
      label: "Amazon Textract",
      description: "AWS-managed OCR with document analysis support.",
      defaultUrl: "https://textract.us-east-1.amazonaws.com",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      modelPlaceholder: "AWS region (e.g., us-east-1)",
      isVerified: true,
    },
    {
      id: "ibm_watson_vision",
      label: "IBM Watson Visual Recognition",
      description: "IBM's visual recognition API with OCR capabilities.",
      defaultUrl: "https://api.us-south.visual-recognition.watson.cloud.ibm.com/v3/detect_text",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      modelPlaceholder: "Service instance ID or version",
      isVerified: true,
    },
    {
      id: "custom",
      label: "Custom provider",
      description: "Point to any OCR endpoint that follows your in-house format.",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: false,
      isVerified: false,
    },
  ],
  translation: [
    {
      id: "system",
      label: "Use site default (recommended)",
      description: "Stay on the site-managed translator for the most reliable experience.",
      requiresKey: false,
      allowsUrl: false,
      allowsModel: false,
      isVerified: true,
    },
    {
      id: "libretranslate_demo",
      label: "LibreTranslate Demo (Free)",
      description: "Community hosted LibreTranslate instance. Great for quick tests.",
      defaultUrl: "https://libretranslate.de/translate",
      requiresKey: false,
      allowsUrl: false,
      allowsModel: false,
      isVerified: true,
    },
    {
      id: "argos_translate_local",
      label: "Argos Translate (Local)",
      description: "Open-source translation models bundled with the desktop app.",
      requiresKey: false,
      allowsUrl: false,
      allowsModel: false,
      isVerified: true,
    },
    {
      id: "google_cloud_translate",
      label: "Google Cloud Translation",
      description: "Enterprise-ready translation API from Google.",
      defaultUrl: "https://translation.googleapis.com/language/translate/v2",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      modelPlaceholder: "Project or glossary ID (optional)",
      isVerified: true,
    },
    {
      id: "azure_translator",
      label: "Microsoft Translator",
      description: "Azure Cognitive Services translation endpoint.",
      defaultUrl: "https://api.cognitive.microsofttranslator.com/translate",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      modelPlaceholder: "Azure region (e.g., eastus)",
      isVerified: true,
    },
    {
      id: "amazon_translate",
      label: "Amazon Translate",
      description: "Neural machine translation through AWS.",
      defaultUrl: "https://translate.amazonaws.com/",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      modelPlaceholder: "AWS region (e.g., us-east-1)",
      isVerified: true,
    },
    {
      id: "ibm_watson_translate",
      label: "IBM Watson Language Translator",
      description: "IBM's translation API with glossary support.",
      defaultUrl: "https://api.us-south.language-translator.watson.cloud.ibm.com/v3/translate",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      modelPlaceholder: "Service instance ID or version",
      isVerified: true,
    },
    {
      id: "custom",
      label: "Custom provider",
      description: "Connect to any REST translation API by supplying the URL and credentials.",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: false,
      isVerified: false,
    },
  ],
  ai: [
    {
      id: "system",
      label: "Use site default (recommended)",
      description: "Let the site decide which AI assistant to use for translations and summaries.",
      requiresKey: false,
      allowsUrl: false,
      allowsModel: false,
      isVerified: true,
    },
    {
      id: "openrouter_free",
      label: "OpenRouter (Free tier)",
      description: "Verified OpenRouter chat completions proxy with free community models.",
      defaultUrl: "https://openrouter.ai/api/v1/chat/completions",
      defaultModel: "openrouter/auto",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "openai_gpt4o",
      label: "OpenAI ChatGPT GPT-4o",
      description: "Flagship multimodal ChatGPT model for complex manga dialogue phrasing and Japanese SFX context.",
      defaultUrl: "https://api.openai.com/v1/chat/completions",
      defaultModel: "gpt-4o",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "openai_gpt4o_mini",
      label: "OpenAI ChatGPT GPT-4o Mini",
      description: "High-speed, low-cost ChatGPT model for instantaneous bulk chapter phrasing.",
      defaultUrl: "https://api.openai.com/v1/chat/completions",
      defaultModel: "gpt-4o-mini",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "openai_o3_mini",
      label: "OpenAI o3-mini / o1 Reasoning",
      description: "Advanced deep-reasoning model for complex martial arts cultivation and archaic dialogue.",
      defaultUrl: "https://api.openai.com/v1/chat/completions",
      defaultModel: "o3-mini",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "anthropic_claude_37",
      label: "Anthropic Claude 3.7 Sonnet",
      description: "State-of-the-art hybrid reasoning model for nuance and natural localization.",
      defaultUrl: "https://api.anthropic.com/v1/messages",
      defaultModel: "claude-3-7-sonnet-20250219",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "anthropic_claude_35",
      label: "Anthropic Claude 3.5 Sonnet",
      description: "Superb prose stylist for fantasy terminology and dialogue translation.",
      defaultUrl: "https://api.anthropic.com/v1/messages",
      defaultModel: "claude-3-5-sonnet-20241022",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "google_gemini_25",
      label: "Google Gemini 2.5 Flash / Pro",
      description: "Ultra-fast multimodal OCR and contextual translation engine.",
      defaultUrl: "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
      defaultModel: "gemini-2.5-flash",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "deepseek_r1",
      label: "DeepSeek R1 / V3 Reasoning (China)",
      description: "Hangzhou DeepSeek AI: World-class open reasoning model specializing in complex Chinese, Japanese, and Korean phrasing.",
      defaultUrl: "https://api.deepseek.com/chat/completions",
      defaultModel: "deepseek-reasoner",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "deepseek_chat",
      label: "DeepSeek V3 Chat (China)",
      description: "Hangzhou DeepSeek AI: Ultra-fast, cost-effective multimodal dialogue model for bulk chapter localization.",
      defaultUrl: "https://api.deepseek.com/chat/completions",
      defaultModel: "deepseek-chat",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "mistral_large",
      label: "Mistral Large 2 (Paris, France)",
      description: "Mistral AI (France): Europe's leading frontier AI model with state-of-the-art multilingual fluency and reasoning.",
      defaultUrl: "https://api.mistral.ai/v1/chat/completions",
      defaultModel: "mistral-large-latest",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "mistral_pixtral",
      label: "Mistral Pixtral 12B Vision (France)",
      description: "Mistral AI (France): Native multimodal vision model tailored for graphic novels, manga panels, and OCR context.",
      defaultUrl: "https://api.mistral.ai/v1/chat/completions",
      defaultModel: "pixtral-12b-2409",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "qwen_plus",
      label: "Alibaba Qwen 2.5 Plus / Max (China)",
      description: "Alibaba Cloud DashScope: Top-performing multilingual model with extensive vocabulary for Asian comic terminologies.",
      defaultUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
      defaultModel: "qwen-plus",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "qwen_vl",
      label: "Alibaba Qwen 2.5 VL Visual (China)",
      description: "Alibaba Cloud DashScope: Specialized visual language model for recognizing text bubbles within complex comic art.",
      defaultUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
      defaultModel: "qwen-vl-max",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "zhipu_glm4",
      label: "Zhipu AI GLM-4 Plus (China)",
      description: "Tsinghua University spin-off Zhipu AI: Premier bilingual foundational model with high literary and fantasy localization accuracy.",
      defaultUrl: "https://open.bigmodel.cn/api/paas/v4/chat/completions",
      defaultModel: "glm-4-plus",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "moonshot_kimi",
      label: "Moonshot AI Kimi v1 (China)",
      description: "Moonshot AI (Beijing): High-capacity context model with superior retention for sprawling multi-arc webtoon storylines.",
      defaultUrl: "https://api.moonshot.cn/v1/chat/completions",
      defaultModel: "moonshot-v1-128k",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "baichuan_4",
      label: "Baichuan 4 (China)",
      description: "Baichuan Intelligence: Renowned Chinese LLM company optimizing natural dialogue syntax and colloquial phrasing.",
      defaultUrl: "https://api.baichuan-ai.com/v1/chat/completions",
      defaultModel: "Baichuan4",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "minimax_text",
      label: "MiniMax abab6.5 (China)",
      description: "MiniMax AI (Shanghai): Character-focused generative engine ideal for diverse character voices and emotional tones.",
      defaultUrl: "https://api.minimax.chat/v1/text/chatcompletion_v2",
      defaultModel: "abab6.5s-chat",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "huggingface_inference",
      label: "Hugging Face Inference (France/USA)",
      description: "Hugging Face Hub: Verified serverless inference router for thousands of open-source language models.",
      defaultUrl: "https://api-inference.huggingface.co/v1/chat/completions",
      defaultModel: "meta-llama/Llama-3.3-70B-Instruct",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "groq_lpu",
      label: "Groq LPU Inference (USA)",
      description: "Groq Cloud: Sub-second conversational generation engine running Llama 3.3 and DeepSeek R1 models at extreme speed.",
      defaultUrl: "https://api.groq.com/openai/v1/chat/completions",
      defaultModel: "llama-3.3-70b-versatile",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "cohere_command",
      label: "Cohere Command R+ (Canada/UK)",
      description: "Cohere AI: Enterprise multilingual multilingual engine designed for factual and nuanced text restructuring.",
      defaultUrl: "https://api.cohere.com/v1/chat",
      defaultModel: "command-r-plus-08-2024",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "together_ai",
      label: "Together AI Cloud (USA)",
      description: "Together.ai: Leading open-model platform with fast endpoints for DeepSeek, Qwen 2.5, and Llama 3.3.",
      defaultUrl: "https://api.together.xyz/v1/chat/completions",
      defaultModel: "deepseek-ai/DeepSeek-V3",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "perplexity_sonar",
      label: "Perplexity Sonar (USA)",
      description: "Perplexity AI: Search-grounded reasoning model for validating cultural trivia and name localizations.",
      defaultUrl: "https://api.perplexity.ai/chat/completions",
      defaultModel: "sonar-pro",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: true,
    },
    {
      id: "custom",
      label: "Custom API Endpoint",
      description: "Connect any verified REST or OpenAI-compatible endpoint from any provider worldwide.",
      requiresKey: true,
      allowsUrl: true,
      allowsModel: true,
      isVerified: false,
    },
  ],
};

const listeners = new Set();
let cachedRegistry = null;

function sanitizeId(value) {
  if (typeof value !== "string") return "";
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_|_$/g, "");
}

function clone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

function normalizeProvider(service, provider, { fallbackVerified = false } = {}) {
  if (!provider || typeof provider !== "object") return null;
  const rawId = provider.id || provider.value || provider.identifier;
  const id = sanitizeId(rawId || provider.label || provider.name);
  if (!id) return null;

  return {
    id,
    service,
    label: provider.label || provider.name || id,
    description: provider.description || "",
    requiresKey: provider.requiresKey === true,
    allowsUrl: provider.allowsUrl === true,
    allowsModel: provider.allowsModel === true,
    defaultUrl: provider.defaultUrl || provider.apiUrl || "",
    defaultModel: provider.defaultModel || provider.model || "",
    modelPlaceholder: provider.modelPlaceholder || "",
    isVerified: provider.isVerified ?? fallbackVerified,
    isBuiltIn: provider.isBuiltIn === true,
  };
}

function createDefaultRegistry() {
  const registry = {};
  for (const [service, providers] of Object.entries(RAW_DEFAULTS)) {
    registry[service] = providers
      .map((provider) =>
        normalizeProvider(service, { ...provider, isBuiltIn: true }, { fallbackVerified: true })
      )
      .filter(Boolean);
  }
  return registry;
}

const DEFAULT_REGISTRY = createDefaultRegistry();

function getStorage() {
  if (typeof window === "undefined" || !window.localStorage) return null;
  return window.localStorage;
}

function sanitizeRegistry(registry) {
  if (!registry || typeof registry !== "object") return {};
  const next = {};
  for (const [service, providers] of Object.entries(registry)) {
    if (!Array.isArray(providers)) continue;
    const sanitized = providers
      .map((provider) => normalizeProvider(service, provider))
      .filter(Boolean);
    if (sanitized.length) {
      next[service] = sanitized;
    }
  }
  return next;
}

function mergeWithDefaults(registry) {
  const sanitized = sanitizeRegistry(registry);
  const merged = {};
  for (const [service, defaults] of Object.entries(DEFAULT_REGISTRY)) {
    const overrides = sanitized[service] || [];
    const map = new Map();
    defaults.forEach((provider) => map.set(provider.id, clone(provider)));
    overrides.forEach((provider) => {
      if (map.has(provider.id)) {
        const base = map.get(provider.id);
        map.set(provider.id, { ...base, ...provider, id: base.id, service });
      } else {
        map.set(provider.id, { ...provider, service, isBuiltIn: false });
      }
    });
    merged[service] = Array.from(map.values());
  }

  for (const [service, providers] of Object.entries(sanitized)) {
    if (merged[service]) continue;
    merged[service] = providers.map((provider) => ({ ...provider, service, isBuiltIn: provider.isBuiltIn === true }));
  }

  return merged;
}

function persistRegistry(registry) {
  const storage = getStorage();
  cachedRegistry = clone(registry);
  if (!storage) return;
  const payload = {};
  for (const [service, providers] of Object.entries(registry)) {
    payload[service] = providers.map(({ service: _service, ...rest }) => rest);
  }
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch (err) {
    console.warn("Failed to persist API registry", err);
  }
}

function notifyListeners(registry) {
  const snapshot = clone(registry);
  listeners.forEach((listener) => {
    try {
      listener(snapshot);
    } catch (err) {
      console.error("apiRegistry listener failed", err);
    }
  });
}

export function loadRegistry() {
  if (cachedRegistry) {
    return clone(cachedRegistry);
  }

  const storage = getStorage();
  if (!storage) {
    cachedRegistry = mergeWithDefaults({});
    return clone(cachedRegistry);
  }

  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) {
      cachedRegistry = mergeWithDefaults({});
      return clone(cachedRegistry);
    }
    const parsed = JSON.parse(raw);
    cachedRegistry = mergeWithDefaults(parsed);
    return clone(cachedRegistry);
  } catch (err) {
    console.warn("Failed to parse API registry", err);
    cachedRegistry = mergeWithDefaults({});
    return clone(cachedRegistry);
  }
}

export function addRegistryListener(listener) {
  if (typeof listener !== "function") return () => {};
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function resetRegistry() {
  const registry = mergeWithDefaults({});
  persistRegistry(registry);
  notifyListeners(registry);
  return { success: true, registry };
}

export function upsertProvider(service, provider) {
  const normalized = normalizeProvider(service, provider);
  if (!normalized) {
    return { success: false, error: "Provider must include an identifier or label." };
  }
  const registry = loadRegistry();
  const current = registry[service] || [];
  const index = current.findIndex((item) => item.id === normalized.id);
  if (index >= 0) {
    const existing = current[index];
    current[index] = {
      ...existing,
      ...normalized,
      id: existing.id,
      service,
      isBuiltIn: existing.isBuiltIn,
    };
  } else {
    current.push({ ...normalized, service, isBuiltIn: normalized.isBuiltIn === true });
  }
  registry[service] = current;
  persistRegistry(registry);
  notifyListeners(registry);
  return { success: true, registry, provider: registry[service][current.findIndex((item) => item.id === normalized.id)] };
}

export function updateProvider(service, id, updates) {
  const sanitizedId = sanitizeId(id);
  if (!sanitizedId) {
    return { success: false, error: "Unknown provider." };
  }
  const registry = loadRegistry();
  const current = registry[service] || [];
  const index = current.findIndex((item) => item.id === sanitizedId);
  if (index === -1) {
    return { success: false, error: "Provider not found." };
  }
  const existing = current[index];
  current[index] = {
    ...existing,
    ...normalizeProvider(service, { ...existing, ...updates, id: sanitizedId }),
    id: existing.id,
    service,
    isBuiltIn: existing.isBuiltIn,
  };
  registry[service] = current;
  persistRegistry(registry);
  notifyListeners(registry);
  return { success: true, registry, provider: current[index] };
}

export function removeProvider(service, id) {
  const sanitizedId = sanitizeId(id);
  if (!sanitizedId) {
    return { success: false, error: "Unknown provider." };
  }
  const registry = loadRegistry();
  const current = registry[service] || [];
  const index = current.findIndex((item) => item.id === sanitizedId);
  if (index === -1) {
    return { success: false, error: "Provider not found." };
  }
  if (current[index].isBuiltIn) {
    return { success: false, error: "Built-in providers cannot be removed." };
  }
  current.splice(index, 1);
  registry[service] = current;
  persistRegistry(registry);
  notifyListeners(registry);
  return { success: true, registry };
}

export function getProviders() {
  return loadRegistry();
}

export function useApiRegistry() {
  const [registry, setRegistry] = useState(() => loadRegistry());

  useEffect(() => {
    setRegistry(loadRegistry());
    const unsubscribe = addRegistryListener(setRegistry);
    function handleStorage(event) {
      if (event.key === STORAGE_KEY) {
        setRegistry(loadRegistry());
      }
    }
    if (typeof window !== "undefined") {
      window.addEventListener("storage", handleStorage);
    }
    return () => {
      unsubscribe();
      if (typeof window !== "undefined") {
        window.removeEventListener("storage", handleStorage);
      }
    };
  }, []);

  const actions = useMemo(
    () => ({
      addProvider: (service, provider) => upsertProvider(service, provider),
      updateProvider: (service, id, updates) => updateProvider(service, id, updates),
      removeProvider: (service, id) => removeProvider(service, id),
      reset: () => resetRegistry(),
    }),
    []
  );

  const value = useMemo(
    () => ({
      registry,
      ...actions,
    }),
    [registry, actions]
  );

  return value;
}

export const __defaults = clone(DEFAULT_REGISTRY);
