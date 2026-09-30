from typing import List, Optional, Any, Dict
from pydantic import BaseModel


class OCRBox(BaseModel):
    x: float
    y: float
    width: Optional[float] = None
    w: Optional[float] = None
    height: Optional[float] = None
    h: Optional[float] = None
    text: Optional[str] = None
    translated_text: Optional[str] = None
    translated: Optional[str] = None


class OCROverlayResponse(BaseModel):
    boxes: List[OCRBox]
    metadata: Optional[Dict[str, Any]] = None
    errors: Optional[List[Any]] = None
    text: Optional[str] = None


class OCRTranslateOverlayRequest(BaseModel):
    image_url: Optional[str] = None
    imageUrl: Optional[str] = None
    target: Optional[str] = None
    targetLang: Optional[str] = None
    source: Optional[str] = None
    sourceLang: Optional[str] = None
    lang: Optional[str] = None
    ocrLang: Optional[str] = None
