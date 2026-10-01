import { formatUtcTime } from "../utils/gstTime";
import React, { useEffect, useMemo, useState } from "react";
import useReaderSettings, { READER_DEFAULTS } from "../hooks/useReaderSettings";
import OverlayBox from "../components/OverlayBox";
import { OVERLAY_FONTS } from "../fonts/overlayFonts";

// Everything about translated pages in one place: on/off, language, how the
// translated text looks, how smart the AI is allowed to be, and how much the
// reader lets it translate per day/week/month.

const LANGUAGES: Array<[string, string]> = [
  ["en", "English"], ["es", "Spanish"], ["fr", "French"], ["de", "German"], ["pt", "Portuguese"],
  ["it", "Italian"], ["ru", "Russian"], ["ar", "Arabic"], ["hi", "Hindi"], ["bn", "Bengali"],
  ["id", "Indonesian"], ["vi", "Vietnamese"], ["th", "Thai"], ["tr", "Turkish"],
  ["ja", "Japanese"], ["ko", "Korean"], ["zh", "Chinese"],
];

const STYLES = [
  { key: "white_box", label: "Blend into the bubble", desc: "Covers the original text with the bubble's own colour. Recommended." },
  { key: "colored_box", label: "My colours", desc: "Your box and text colours on every bubble." },
  { key: "transparent_box", label: "See-through", desc: "Dark glass over the text; the art stays visible." },
];

const card = "bg-[#15171c] border border-[#262a33] rounded-2xl p-5 shadow-xl space-y-4 text-xs";
const label = "font-bold text-gray-300 block mb-1";
const select =
  "w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]";

function Toggle({ checked, onChange, title, desc }: { checked: boolean; onChange: (v: boolean) => void; title: string; desc: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="w-full flex items-start justify-between gap-4 p-3 rounded-xl bg-[#101216] border border-[#262a33] text-left hover:border-[#00AEF0]/50 transition"
    >
      <span>
        <span className="block text-xs font-bold text-white">{title}</span>
        <span className="block text-[11px] text-[#8b93a3] mt-0.5">{desc}</span>
      </span>
      <span className={`mt-0.5 shrink-0 w-10 h-6 rounded-full p-0.5 transition ${checked ? "bg-[#00AEF0]" : "bg-[#262a33]"}`}>
        <span className={`block w-5 h-5 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-4" : ""}`}></span>
      </span>
    </button>
  );
}

function ColorField({ value, onChange, autoLabel }: { value: string | null; onChange: (v: string | null) => void; autoLabel: string }) {
  return (
    <div className="flex items-center gap-2">
      <input
        type="color"
        value={value || "#ffffff"}
        onChange={(e) => onChange(e.target.value)}
        className="w-10 h-9 rounded-lg bg-[#101216] border border-[#262a33] cursor-pointer"
      />
      <button
        type="button"
        onClick={() => onChange(null)}
        className={`px-3 py-2 rounded-xl border text-[11px] font-semibold transition ${
          value ? "border-[#262a33] text-gray-400 hover:text-white" : "border-[#00AEF0] text-[#00AEF0] bg-[#00AEF0]/10"
        }`}
      >
        {autoLabel}
      </button>
      {value && <span className="font-mono text-[11px] text-gray-400">{value}</span>}
    </div>
  );
}

export default function ReadingSettings() {
  const { settings, loaded, error, save, saving } = useReaderSettings();
  const [draft, setDraft] = useState<any>(READER_DEFAULTS);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  // Reset the form whenever fresh server data arrives (first load, a save,
  // or a size change made from the reader).
  const serverKey = JSON.stringify(settings);
  useEffect(() => {
    if (loaded) setDraft(JSON.parse(serverKey));
  }, [loaded, serverKey]);

  const set = (patch: Record<string, any>) => {
    setDraft((d: any) => ({ ...d, ...patch }));
    setNotice(null);
  };

  const hasLimit = draft.usage_limit_value != null;
  const dirty = useMemo(
    () =>
      [
        "overlay_enabled", "target_language", "overlay_style", "overlay_font", "overlay_font_size",
        "overlay_text_color", "overlay_box_color", "overlay_box_opacity", "context_translation",
        "ai_assist_enabled", "translate_sound_effects", "usage_limit_unit", "usage_limit_window",
        "usage_limit_value",
      ].some((k) => (draft as any)[k] !== (settings as any)[k]),
    [draft, settings]
  );

  const onSave = async () => {
    try {
      await save({
        overlay_enabled: draft.overlay_enabled,
        target_language: draft.target_language,
        overlay_style: draft.overlay_style,
        overlay_font: draft.overlay_font,
        overlay_font_size: draft.overlay_font_size,
        overlay_text_color: draft.overlay_text_color || "",
        overlay_box_color: draft.overlay_box_color || "",
        overlay_box_opacity: draft.overlay_box_opacity,
        context_translation: draft.context_translation,
        ai_assist_enabled: draft.ai_assist_enabled,
        translate_sound_effects: draft.translate_sound_effects,
        usage_limit_unit: draft.usage_limit_unit,
        usage_limit_window: draft.usage_limit_window,
        ...(hasLimit ? { usage_limit_value: draft.usage_limit_value } : { clear_usage_limit: true }),
      });
      setNotice({ ok: true, text: "Saved. Open any chapter and the pages translate automatically." });
    } catch (err: any) {
      setNotice({ ok: false, text: err?.message || "Could not save." });
    }
  };

  if (error) return <p className="text-xs text-red-400">Could not load your reading settings. Are you signed in?</p>;
  if (!loaded) return <p className="text-xs text-[#8b93a3]">Loading…</p>;

  const used = settings.usage_current ?? 0;
  const limit = settings.usage_limit_value;
  const unitLabel = draft.usage_limit_unit === "words" ? "words" : "pages";
  const windowLabel = { day: "day", week: "week", month: "month" }[draft.usage_limit_window as string] || "day";
  const preview = {
    translated: "I won't lose to a bug like you!",
    bg: "#ffffff",
    fg: "#111111",
  };

  return (
    <div className="space-y-5">
      {/* 1. On/off and language */}
      <section className={card}>
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <i className="fas fa-language text-[#00AEF0]"></i> Automatic page translation
        </h3>
        <Toggle
          checked={draft.overlay_enabled}
          onChange={(v) => set({ overlay_enabled: v })}
          title="Translate pages when I open a chapter"
          desc="The translation appears over the original text. No button to press in the reader."
        />
        <div className="max-w-xs">
          <label className={label}>Translate into</label>
          <select value={draft.target_language} onChange={(e) => set({ target_language: e.target.value })} className={select}>
            {LANGUAGES.map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </div>
      </section>

      {/* 2. Look */}
      <section className={card}>
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <i className="fas fa-font text-[#00AEF0]"></i> How translated text looks
        </h3>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div className="space-y-4">
            <div>
              <label className={label}>Font</label>
              <div className="grid grid-cols-2 gap-2">
                {OVERLAY_FONTS.map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => set({ overlay_font: f.id })}
                    className={`px-3 py-2 rounded-xl border text-left transition ${
                      draft.overlay_font === f.id
                        ? "border-[#00AEF0] bg-[#00AEF0]/10 text-white"
                        : "border-[#262a33] bg-[#101216] text-gray-300 hover:text-white"
                    }`}
                    style={{ fontFamily: f.css_family, fontWeight: f.weight }}
                  >
                    <span className="block text-sm leading-tight">Hey! Wait!</span>
                    <span className="block text-[10px] text-[#8b93a3] font-sans font-normal mt-0.5">{f.label}</span>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between">
                <label className={label}>Largest text size</label>
                <span className="font-mono font-bold text-[#00AEF0]">{draft.overlay_font_size}px</span>
              </div>
              <input
                type="range"
                min={10}
                max={40}
                value={draft.overlay_font_size}
                onChange={(e) => set({ overlay_font_size: Number(e.target.value) })}
                className="w-full accent-[#00AEF0]"
              />
              <p className="text-[10px] text-[#8b93a3]">Long lines shrink automatically to fit the original text area.</p>
            </div>

            <div>
              <label className={label}>Box style</label>
              <div className="space-y-2">
                {STYLES.map((st) => (
                  <button
                    key={st.key}
                    type="button"
                    onClick={() => set({ overlay_style: st.key })}
                    className={`w-full p-2.5 rounded-xl border text-left transition ${
                      draft.overlay_style === st.key
                        ? "bg-[#00AEF0]/10 border-[#00AEF0]"
                        : "bg-[#101216] border-[#262a33] hover:border-[#00AEF0]/50"
                    }`}
                  >
                    <span className="block text-xs font-bold text-white">{st.label}</span>
                    <span className="block text-[10px] text-[#8b93a3]">{st.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={label}>Text colour</label>
                <ColorField value={draft.overlay_text_color} onChange={(v) => set({ overlay_text_color: v })} autoLabel="Automatic" />
              </div>
              {draft.overlay_style !== "transparent_box" && (
                <div>
                  <label className={label}>Box colour</label>
                  <ColorField
                    value={draft.overlay_box_color}
                    onChange={(v) => set({ overlay_box_color: v })}
                    autoLabel={draft.overlay_style === "white_box" ? "Match bubble" : "White"}
                  />
                </div>
              )}
            </div>

            {draft.overlay_style !== "transparent_box" && (
              <div>
                <div className="flex items-center justify-between">
                  <label className={label}>Box opacity</label>
                  <span className="font-mono font-bold text-[#00AEF0]">{draft.overlay_box_opacity}%</span>
                </div>
                <input
                  type="range"
                  min={40}
                  max={100}
                  value={draft.overlay_box_opacity}
                  onChange={(e) => set({ overlay_box_opacity: Number(e.target.value) })}
                  className="w-full accent-[#00AEF0]"
                />
                <p className="text-[10px] text-[#8b93a3]">100% fully hides the original lettering.</p>
              </div>
            )}
          </div>

          {/* Live preview: a bubble with the original lettering, covered exactly like the reader does it. */}
          <div className="space-y-2">
            <label className={label}>Preview</label>
            <div className="relative rounded-2xl border border-[#262a33] bg-[radial-gradient(#2a2f3a_1px,transparent_1px)] [background-size:14px_14px] bg-[#0a0c0f] h-64 flex items-center justify-center overflow-hidden">
              <div className="relative w-64 h-40 rounded-[50%] bg-white shadow-xl flex items-center justify-center">
                <span className="text-black text-lg font-bold leading-tight text-center">
                  저딴 벌레한테
                  <br />
                  밀리고 있다고?
                </span>
                <OverlayBox
                  region={preview}
                  settings={draft}
                  style={{ left: "17%", top: "26%", width: "66%", height: "48%" }}
                />
              </div>
            </div>
            <p className="text-[10px] text-[#8b93a3]">
              Only the text area is covered; the rest of the art stays untouched.
            </p>
          </div>
        </div>
      </section>

      {/* 3. AI */}
      <section className={card}>
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <i className="fas fa-brain text-purple-400"></i> AI help
        </h3>
        <Toggle
          checked={draft.context_translation}
          onChange={(v) => set({ context_translation: v })}
          title="Understand the conversation (context-aware AI)"
          desc="The AI reads the whole page, keeps names, pronouns and tone consistent, and makes dialogue sound natural. Off = plain line-by-line translation (uses less of your AI quota)."
        />
        <Toggle
          checked={draft.ai_assist_enabled}
          onChange={(v) => set({ ai_assist_enabled: v })}
          title="Let the AI re-read unclear text"
          desc="When OCR is unsure about a bubble, the AI looks at the picture and reads it again."
        />
        <Toggle
          checked={draft.translate_sound_effects}
          onChange={(v) => set({ translate_sound_effects: v })}
          title="Translate sound effects"
          desc="BOOM, CRASH and similar lettering drawn into the art."
        />
        <p className="text-[10px] text-[#8b93a3]">These need an AI key in AI &amp; OCR Engines.</p>
      </section>

      {/* 4. Limit */}
      <section className={card}>
        <h3 className="text-sm font-bold text-white flex items-center gap-2">
          <i className="fas fa-tachometer-alt text-amber-400"></i> Translation limit
        </h3>
        <Toggle
          checked={hasLimit}
          onChange={(v) => set({ usage_limit_value: v ? settings.usage_limit_value || 50 : null })}
          title="Limit how much gets translated"
          desc="Protects your API quota or bill. When the limit is reached, pages show untranslated until it resets."
        />
        {hasLimit && (
          <div className="space-y-3">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className={label}>Up to</label>
                <input
                  type="number"
                  min={1}
                  value={draft.usage_limit_value ?? ""}
                  onChange={(e) => set({ usage_limit_value: Math.max(1, Number(e.target.value) || 1) })}
                  className={select}
                />
              </div>
              <div>
                <label className={label}>Counting</label>
                <select value={draft.usage_limit_unit} onChange={(e) => set({ usage_limit_unit: e.target.value })} className={select}>
                  <option value="pages">Pages</option>
                  <option value="words">Words</option>
                </select>
              </div>
              <div>
                <label className={label}>Per</label>
                <select value={draft.usage_limit_window} onChange={(e) => set({ usage_limit_window: e.target.value })} className={select}>
                  <option value="day">Day</option>
                  <option value="week">Week</option>
                  <option value="month">Month</option>
                </select>
              </div>
            </div>
            <input
              type="range"
              min={1}
              max={draft.usage_limit_unit === "words" ? 20000 : 500}
              step={draft.usage_limit_unit === "words" ? 100 : 1}
              value={draft.usage_limit_value ?? 1}
              onChange={(e) => set({ usage_limit_value: Number(e.target.value) })}
              className="w-full accent-amber-400"
            />
            <p className="text-[11px] text-gray-300">
              Up to <b>{draft.usage_limit_value}</b> {unitLabel} per {windowLabel}.
            </p>
          </div>
        )}
        {limit != null && (
          <div className="space-y-1">
            <div className="h-2 rounded-full bg-[#101216] overflow-hidden border border-[#262a33]">
              <div
                className="h-full bg-amber-400"
                style={{ width: `${Math.min(100, Math.round((used / Math.max(1, limit)) * 100))}%` }}
              ></div>
            </div>
            <p className="text-[10px] text-[#8b93a3]">
              Used {used} of {limit} {settings.usage_limit_unit} this {settings.usage_limit_window}
              {settings.usage_reset_at ? ` · resets ${formatUtcTime(settings.usage_reset_at)}` : ""}.
            </p>
          </div>
        )}
      </section>

      <div className="sticky bottom-3 z-10 flex items-center justify-end gap-3 p-3 rounded-2xl bg-[#15171c]/95 border border-[#262a33] backdrop-blur">
        {notice && <span className={`mr-auto text-xs ${notice.ok ? "text-emerald-400" : "text-red-400"}`}>{notice.text}</span>}
        {dirty && !notice && <span className="mr-auto text-xs text-amber-300">Unsaved changes</span>}
        <button
          type="button"
          disabled={!dirty || saving}
          onClick={() => setDraft(settings)}
          className="px-4 py-2 rounded-xl border border-[#262a33] text-xs text-gray-300 hover:text-white disabled:opacity-40"
        >
          Reset
        </button>
        <button
          type="button"
          disabled={!dirty || saving}
          onClick={onSave}
          className="px-5 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs shadow-lg transition flex items-center gap-1.5 disabled:opacity-40"
        >
          <i className={saving ? "fas fa-spinner fa-spin" : "fas fa-save"}></i>
          <span>{saving ? "Saving…" : "Save settings"}</span>
        </button>
      </div>
    </div>
  );
}
