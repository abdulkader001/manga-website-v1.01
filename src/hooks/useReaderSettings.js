import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../services/api";

// The reader's translation/overlay preferences, stored on their account
// (GET/PUT /user/processing-settings). Shared through React Query so the
// Settings page, the reader and every page overlay see one copy.

export const READER_SETTINGS_KEY = ["readerSettings"];

export const READER_DEFAULTS = {
  overlay_enabled: true,
  target_language: "en",
  overlay_style: "white_box",
  overlay_font: "standard_sans",
  overlay_font_size: 20,
  overlay_text_color: null,
  overlay_box_color: null,
  overlay_box_opacity: 100,
  context_translation: true,
  ai_assist_enabled: false,
  translate_sound_effects: true,
  usage_limit_unit: "pages",
  usage_limit_window: "day",
  usage_limit_value: null,
};

export default function useReaderSettings({ enabled = true } = {}) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: READER_SETTINGS_KEY,
    queryFn: () => api.user.getProcessingSettings(),
    enabled,
    staleTime: 60_000,
    retry: false,
  });

  const mutation = useMutation({
    mutationFn: (/** @type {Record<string, any>} */ changes) => api.user.updateProcessingSettings(changes),
    onSuccess: (data) => queryClient.setQueryData(READER_SETTINGS_KEY, data),
  });

  return {
    settings: { ...READER_DEFAULTS, ...(query.data || {}) },
    loaded: query.isSuccess,
    error: query.error,
    save: mutation.mutateAsync,
    saving: mutation.isPending,
  };
}
