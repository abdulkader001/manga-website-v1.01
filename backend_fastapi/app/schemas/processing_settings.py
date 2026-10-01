from typing import Optional

from pydantic import BaseModel, Field


class ProcessingSettingsResponse(BaseModel):
    usage_limit_unit: str
    usage_limit_window: str
    usage_limit_value: Optional[int] = None
    usage_current: int
    ai_usage_current: int
    usage_period_start: Optional[str] = None
    # Computed for display convenience (Settings screen, 2E.1A/2E.2).
    usage_remaining: Optional[int] = None
    usage_reset_at: Optional[str] = None
    ai_usage_remaining: Optional[int] = None
    ai_assist_enabled: bool
    ai_confidence_threshold: float
    share_translations: bool
    overlay_style: str
    overlay_font: str
    overlay_font_size: int
    translate_sound_effects: bool
    auto_translate_comments: bool = True
    overlay_enabled: bool = True
    target_language: str = "en"
    overlay_text_color: Optional[str] = None
    overlay_box_color: Optional[str] = None
    overlay_box_opacity: int = 100
    context_translation: bool = True


class UpdateProcessingSettingsRequest(BaseModel):
    usage_limit_unit: Optional[str] = None
    usage_limit_window: Optional[str] = None
    usage_limit_value: Optional[int] = Field(default=None)
    ai_assist_enabled: Optional[bool] = None
    ai_confidence_threshold: Optional[float] = None
    share_translations: Optional[bool] = None
    overlay_style: Optional[str] = None
    overlay_font: Optional[str] = None
    overlay_font_size: Optional[int] = None
    translate_sound_effects: Optional[bool] = None
    auto_translate_comments: Optional[bool] = None
    # Explicit, because a null usage_limit_value is indistinguishable from
    # "not sent" once None fields are dropped.
    clear_usage_limit: Optional[bool] = None
    overlay_enabled: Optional[bool] = None
    target_language: Optional[str] = Field(default=None, max_length=8)
    # "" resets a colour to automatic.
    overlay_text_color: Optional[str] = Field(default=None, max_length=7)
    overlay_box_color: Optional[str] = Field(default=None, max_length=7)
    overlay_box_opacity: Optional[int] = None
    context_translation: Optional[bool] = None


__all__ = ["ProcessingSettingsResponse", "UpdateProcessingSettingsRequest"]
