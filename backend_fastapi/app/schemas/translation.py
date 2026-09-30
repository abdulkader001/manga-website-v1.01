from typing import Optional, Any, Dict
from pydantic import BaseModel


class TranslationRequest(BaseModel):
    text: str
    # Optional series context. When present, the translation rights gate
    # (SRS 1J) is enforced: a series marked not translatable is rejected.
    manga_id: Optional[int] = None
    mangaId: Optional[int] = None
    target: Optional[str] = None
    target_lang: Optional[str] = None
    targetLang: Optional[str] = None
    source: Optional[str] = None
    source_lang: Optional[str] = None
    sourceLang: Optional[str] = None
    provider_config: Optional[Dict[str, Any]] = None
    providerConfig: Optional[Dict[str, Any]] = None
    provider: Optional[str] = None
    provider_id: Optional[str] = None
    providerId: Optional[str] = None


class TranslationResponse(BaseModel):
    translated: str
    # SRS 1H.8.2: "tell users the truth" — set when the platform default was
    # used because the caller's own provider didn't respond.
    used_fallback: bool = False
    # A human-readable note for the fallback case; never a blank overlay.
    notice: Optional[str] = None


class TranslationErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    limit: Optional[int] = None
