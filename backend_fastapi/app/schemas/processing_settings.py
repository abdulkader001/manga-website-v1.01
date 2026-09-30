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


__all__ = ["ProcessingSettingsResponse", "UpdateProcessingSettingsRequest"]
