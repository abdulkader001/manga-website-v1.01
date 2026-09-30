from typing import Dict, Any, Optional
from pydantic import BaseModel


class UserSettingsResponse(BaseModel):
    email: Optional[str] = None
    email_masked: Optional[str] = None
    profile_image: Optional[str] = None
    language: Optional[str] = None
    username: Optional[str] = None
    api_keys: Dict[str, Any]


class UpdateUserSettingsRequest(BaseModel):
    avatarUrl: Optional[str] = None
    avatar_url: Optional[str] = None
    preferredLanguage: Optional[str] = None
    preferred_language: Optional[str] = None
    profile_image: Optional[str] = None
    username: Optional[str] = None
    language: Optional[str] = None
    api_keys: Optional[Dict[str, Any]] = None
    apiProviders: Optional[Dict[str, Any]] = None
    api_providers: Optional[Dict[str, Any]] = None
    ocr: Optional[Any] = None
    translation: Optional[Any] = None
    ai: Optional[Any] = None
    ocr_api: Optional[Any] = None
    translation_api: Optional[Any] = None
    ai_api: Optional[Any] = None


class UpdateUserAPIKeysResponse(BaseModel):
    success: bool
    api_keys: Dict[str, Any]


class UploadProfileImageResponse(BaseModel):
    profile_image: Optional[str] = None
    email: Optional[str] = None
    email_masked: Optional[str] = None
    username: Optional[str] = None
