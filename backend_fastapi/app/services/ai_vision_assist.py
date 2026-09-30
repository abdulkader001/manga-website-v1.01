"""AI-assisted OCR correction (SRS 2A.3): re-read flagged regions of the page
image via a vision-capable AI provider when OCR failed or fell below the
confidence threshold there. Supports the two chat-completion vision content
shapes already used by this codebase's AI provider config (OpenAI-style
``image_url``, Google Gemini ``inline_data``); any other provider is skipped
-- callers still get to mark the region as flagged even when no working
vision call could be made, rather than fabricating a correction.

Two entry points, one per mode ``ai_assist.plan_ai_assist`` can return:

  - ``assist_region()`` -- ``"per_region"``: crop one region, one call, one
    string back. A handful of regions on an otherwise-readable page.
  - ``assist_page()``   -- ``"whole_page"``: the full page image once, with
    every flagged region's box listed in a structured prompt, and one JSON
    array covering all of them back. This is the mode that fires when OCR
    failed broadly, i.e. exactly when the per-region loop would be at its
    most expensive.
"""

from __future__ import annotations

import base64
import io
import json
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import requests

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

VISION_CAPABLE_PROVIDERS = {"google_gemini", "openai_gpt_3_5", "openai", "custom"}

# A page with more flagged regions than this is pathological OCR output; a
# prompt listing them all would cost more than the re-read is worth.
MAX_PAGE_REGIONS = 200

# The page goes to the provider whole, so bound its longest side. Region
# boxes are scaled by the same factor, so the coordinates the model is given
# always describe the image the model is actually looking at.
MAX_PAGE_IMAGE_DIM = 1600

_CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def _crop_region(image: "Image.Image", box: Dict[str, float], margin: int = 8) -> bytes:
    width, height = image.size
    left = max(0, int(box["x"]) - margin)
    top = max(0, int(box["y"]) - margin)
    right = min(width, int(box["x"] + box["width"]) + margin)
    bottom = min(height, int(box["y"] + box["height"]) + margin)
    if right <= left or bottom <= top:
        right, bottom = width, height
        left, top = 0, 0
    cropped = image.crop((left, top, right, bottom))
    buffer = io.BytesIO()
    cropped.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def _encode_page(image: "Image.Image") -> Tuple[bytes, float]:
    """Encode the whole page as PNG, downscaled to ``MAX_PAGE_IMAGE_DIM``.

    Returns the bytes and the scale factor applied, so region boxes can be
    moved into the same coordinate space before they are described to the
    model.
    """

    width, height = image.size
    longest = max(width, height)
    scale = 1.0
    page = image
    if longest > MAX_PAGE_IMAGE_DIM:
        scale = MAX_PAGE_IMAGE_DIM / float(longest)
        page = image.resize(
            (max(1, int(width * scale)), max(1, int(height * scale))),
            Image.LANCZOS,
        )
    buffer = io.BytesIO()
    page.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue(), scale


def _scaled_box(box: Dict[str, float], scale: float) -> Dict[str, int]:
    return {
        "x": int(round(float(box.get("x", 0)) * scale)),
        "y": int(round(float(box.get("y", 0)) * scale)),
        "width": int(round(float(box.get("width", 0)) * scale)),
        "height": int(round(float(box.get("height", 0)) * scale)),
    }


def _build_page_prompt(
    regions: Sequence[Dict[str, Any]],
    image_size: Tuple[int, int],
    language_hint: Optional[str],
) -> str:
    """The structured prompt: one page, several regions, one JSON reply.

    Deliberately the same request/response shape as the translation coherence
    pass (``translation_service.build_coherence_payload``): a list of regions
    keyed by ``index`` in, a ``{"regions": [{"index", ...}]}`` array out, with
    an explicit no-merging/no-reordering rule -- because the reply is spliced
    back onto page regions by index in exactly the same way.
    """

    graph_prompt = {
        "image_size": {"width": image_size[0], "height": image_size[1]},
        "language": language_hint or "",
        "regions": list(regions),
    }
    return (
        "This is a full manga page. OCR could not read the regions listed "
        "below reliably. Each is given by its index and its bounding box in "
        "this image's pixel coordinates, origin at the top-left. Transcribe "
        "exactly the text visible inside each listed region, in its original "
        "language" + (f" ({language_hint})" if language_hint else "") + ".\n\n"
        "These rules are absolute:\n"
        "1. Produce exactly one output entry per listed region index. Never "
        "merge two regions into one, never split one region across two, "
        "never reorder them.\n"
        "2. Region N's text is only the text inside region N's box. Do not "
        "move words between regions.\n"
        "3. A region with no legible text produces an empty string.\n"
        "4. Reply with JSON and nothing else, in exactly this shape:\n"
        '{"regions": [{"index": <int>, "text": "<string>"}]}\n\n'
        + json.dumps(graph_prompt, ensure_ascii=False)
    )


def _vision_request(
    provider_id: str, model: Optional[str], image_b64: str, prompt: str
) -> Dict[str, Any]:
    """One image plus one text prompt, in whichever vision content shape the
    provider speaks. Shared by both modes -- only the prompt differs."""

    if provider_id == "google_gemini":
        return {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/png", "data": image_b64}},
                    ]
                }
            ]
        }
    return {
        "model": model or "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            }
        ],
    }


def _build_payload(
    provider_id: str, model: Optional[str], image_b64: str, language_hint: Optional[str]
) -> Dict[str, Any]:
    prompt = (
        "This is a cropped region from a manga page that OCR could not read "
        "reliably. Transcribe exactly the text visible in the image, in its "
        "original language" + (f" ({language_hint})" if language_hint else "") + ". "
        "Return only the transcribed text, nothing else."
    )
    return _vision_request(provider_id, model, image_b64, prompt)


def _extract_text(provider_id: str, data: Dict[str, Any]) -> Optional[str]:
    if provider_id == "google_gemini":
        candidates = data.get("candidates")
        if isinstance(candidates, list) and candidates:
            parts = candidates[0].get("content", {}).get("parts")
            if isinstance(parts, list) and parts:
                text = parts[0].get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return None
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
    return None


def assist_region(
    image: Optional["Image.Image"],
    box: Dict[str, float],
    *,
    provider_config: Dict[str, Any],
    language_hint: Optional[str] = None,
    timeout: int = 20,
    http_post: Callable[..., Any] = requests.post,
) -> Optional[str]:
    """Return the AI's best-guess transcription for one region, or None if
    no vision-capable provider is configured or the call didn't yield
    usable text."""

    if Image is None or image is None:
        return None
    provider_id = (provider_config.get("provider") or "").strip().lower()
    if provider_id not in VISION_CAPABLE_PROVIDERS:
        return None
    api_url = provider_config.get("api_url")
    if not api_url:
        return None

    crop_bytes = _crop_region(image, box)
    image_b64 = base64.b64encode(crop_bytes).decode("ascii")
    payload = _build_payload(
        provider_id, provider_config.get("model"), image_b64, language_hint
    )

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    api_key = provider_config.get("api_key")
    if api_key:
        if provider_id == "google_gemini":
            headers["X-Goog-Api-Key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = http_post(api_url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return None

    return _extract_text(provider_id, data)


def _parse_page_response(
    content: Optional[str], expected_indices: Sequence[int]
) -> Dict[int, str]:
    """Map the batched reply back onto region indices.

    Unlike the translation coherence pass -- which discards a partial reply
    outright, because a misaligned *translation* silently corrupts the whole
    page -- a partial reply is safe here: every entry is keyed by the index
    it belongs to, and any region the model didn't answer for simply keeps
    the OCR text it already had. So unknown and duplicate indices are
    dropped rather than failing the batch.
    """

    if not content:
        return {}
    stripped = _CODE_FENCE.sub("", content.strip())
    try:
        parsed = json.loads(stripped)
    except (ValueError, TypeError):
        return {}

    entries: Any = parsed
    if isinstance(parsed, dict):
        entries = parsed.get("regions")
    if not isinstance(entries, list):
        return {}

    expected = set(expected_indices)
    corrections: Dict[int, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw_index = entry.get("index")
        if isinstance(raw_index, bool) or not isinstance(raw_index, (int, float)):
            continue
        index = int(raw_index)
        if index not in expected or index in corrections:
            continue
        text = entry.get("text")
        if text is None:
            text = entry.get("translation")
        if not isinstance(text, str) or not text.strip():
            continue
        corrections[index] = text.strip()
    return corrections


def assist_page(
    image: Optional["Image.Image"],
    flagged_regions: Sequence[Dict[str, Any]],
    *,
    provider_config: Dict[str, Any],
    language_hint: Optional[str] = None,
    timeout: int = 40,
    http_post: Optional[Callable[..., Any]] = None,
) -> Dict[int, str]:
    """F-15: one combined page-level vision call covering every flagged
    region, instead of one ``assist_region()`` call per index.

    ``flagged_regions`` is a sequence of normalized region dicts, each with
    an ``index`` and a ``coordinates`` box. Returns ``{index: text}`` for
    the regions the provider actually transcribed -- empty when no vision-
    capable provider is configured or the call yielded nothing usable, in
    which case every region keeps its OCR text.

    The page is sent once and reasoned over as a whole, so this legitimately
    takes longer than a single-region crop; hence the larger default timeout.

    ``http_post`` defaults to ``requests.post``, resolved at call time rather
    than bound as a default argument, so callers that don't inject a
    transport can still be observed by patching this module's ``requests``.
    """

    if Image is None or image is None:
        return {}
    provider_id = (provider_config.get("provider") or "").strip().lower()
    if provider_id not in VISION_CAPABLE_PROVIDERS:
        return {}
    api_url = provider_config.get("api_url")
    if not api_url:
        return {}

    boxed = [
        region
        for region in (flagged_regions or [])
        if isinstance(region.get("coordinates"), dict)
    ]
    if not boxed or len(boxed) > MAX_PAGE_REGIONS:
        return {}

    page_bytes, scale = _encode_page(image)
    image_b64 = base64.b64encode(page_bytes).decode("ascii")
    width, height = image.size
    scaled_size = (max(1, int(width * scale)), max(1, int(height * scale)))

    prompt_regions: List[Dict[str, Any]] = []
    expected: List[int] = []
    for position, region in enumerate(boxed):
        index = int(region.get("index", position))
        expected.append(index)
        prompt_regions.append(
            {"index": index, "box": _scaled_box(region["coordinates"], scale)}
        )

    payload = _vision_request(
        provider_id,
        provider_config.get("model"),
        image_b64,
        _build_page_prompt(prompt_regions, scaled_size, language_hint),
    )

    headers: Dict[str, str] = {"Content-Type": "application/json"}
    api_key = provider_config.get("api_key")
    if api_key:
        if provider_id == "google_gemini":
            headers["X-Goog-Api-Key"] = api_key
        else:
            headers["Authorization"] = f"Bearer {api_key}"

    post = http_post or requests.post
    try:
        response = post(api_url, json=payload, headers=headers, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return {}

    return _parse_page_response(_extract_text(provider_id, data), expected)


__all__ = [
    "assist_region",
    "assist_page",
    "VISION_CAPABLE_PROVIDERS",
    "MAX_PAGE_REGIONS",
    "MAX_PAGE_IMAGE_DIM",
]
