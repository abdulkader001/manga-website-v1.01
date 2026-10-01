"""Translation service abstraction for FastAPI.

Two stages, not one (SRS 2C.1, closing F-12):

  Stage A -- the literal draft. Whatever provider the caller resolved
  (chat-completion or a plain ``q=``/``translate`` REST endpoint, system
  default or the user's own) produces a straight per-region translation.
  This is ``translate()`` and it is unchanged.

  Stage B -- the coherence pass. ``coherence_pass()`` takes every region of
  a page *together* with the glossary, the region types, the previous
  page's closing lines and a chapter summary, and rewrites the literal
  drafts so the page reads as one scene. It is **always** a
  chat-completion call, chosen independently of whatever Stage A used --
  which is what stops F-12 (whole-chapter context silently dropped by the
  plain-MT branch) from recurring: a non-chat provider can still produce
  the draft, but it is never the thing asked to apply context.

Stage B is best-effort by construction. When no chat-completion-capable
provider is configured, or the call/response fails validation, it returns
``None`` and the caller keeps Stage A's drafts.
"""

from __future__ import annotations

import json
import re
import structlog
from typing import Any, Dict, List, Optional, Sequence

import requests

logger = structlog.get_logger("translation_service")

# The construction prompt: fixed rules that make the model's output safe to
# splice back into the page region-by-region. Every rule here exists because
# violating it corrupts the overlay rather than merely reading worse.
COHERENCE_SYSTEM_PROMPT = """You are a manga localization editor performing a coherence pass.

You are given every text region of a single page: its source text and a literal machine translation, in reading order, plus the context needed to make the page read as one scene. Rewrite each literal translation so the page reads naturally and consistently.

These rules are absolute:
1. Produce exactly one output entry per input region. Never merge two regions into one, never split one region across two, never reorder them.
2. Region N's output translates region N's source_text only. Do not move words between regions to make a sentence flow better.
3. An empty source_text produces an empty translation.
4. Match the register to region_type: dialogue/speech_bubble reads as a spoken line, thought as interior monologue, narration as prose, sfx as an onomatopoeia, sign as the literal wording written on the object.
5. Glossary terms are fixed. Render every glossary entry exactly as given, every time it occurs -- never re-translate, abbreviate or substitute it.
6. context.previous_page_last_lines and context.chapter_summary are background only. Never translate them and never echo them back.
7. Reply with JSON and nothing else, in exactly this shape:
{"regions": [{"index": <int>, "translation": "<string>"}]}
"""

# Bound the graph prompt: a page with more regions than this is pathological
# OCR output, and sending it would cost more than the coherence is worth.
MAX_COHERENCE_REGIONS = 200

_CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def build_coherence_payload(
    *,
    target_lang: str,
    regions: Sequence[Dict[str, Any]],
    glossary: Optional[Dict[str, str]] = None,
    previous_page_last_lines: Optional[Sequence[str]] = None,
    chapter_summary: Optional[str] = None,
) -> Dict[str, Any]:
    """The graph prompt: the structured view of one page Stage B reasons over.

    Kept as a module-level function (rather than inlined in the request
    builder) so the exact shape sent to a provider is directly assertable in
    tests -- the shape *is* the contract the system prompt's rules refer to.
    """

    return {
        "target_language": target_lang,
        "glossary": dict(glossary or {}),
        "regions": [
            {
                "index": region.get("index"),
                "reading_order": region.get("reading_order"),
                "region_type": region.get("region_type"),
                "source_text": region.get("source_text") or "",
                "literal_translation": region.get("literal_translation") or "",
            }
            for region in regions
        ],
        "context": {
            "previous_page_last_lines": [
                line for line in (previous_page_last_lines or []) if str(line).strip()
            ],
            "chapter_summary": chapter_summary or "",
        },
    }


class TranslationProviderError(Exception):
    """Raised when a translation provider returns an error or invalid response."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    def __str__(self) -> str:  # pragma: no cover - convenience for logging
        base = super().__str__()
        if self.status_code is not None:
            return f"{base} (status={self.status_code})"
        return base


class TranslationService:
    def __init__(
        self,
        default_api_url: Optional[str],
        default_api_key: Optional[str] = None,
        *,
        default_provider_config: Optional[Dict[str, Any]] = None,
        timeout_s: int = 12,
        coherence_timeout_s: Optional[int] = None,
    ) -> None:
        self.default_api_url = default_api_url
        self.default_api_key = default_api_key
        self.timeout_s = timeout_s
        # Stage B reasons over a whole page in one call, so it legitimately
        # takes longer than a single-region Stage A request.
        self.coherence_timeout_s = coherence_timeout_s or max(timeout_s * 2, 30)

        base_default: Dict[str, Any] = {}
        if isinstance(default_provider_config, dict):
            base_default.update(default_provider_config)
        if default_api_url:
            base_default["api_url"] = default_api_url
        if default_api_key is not None:
            base_default["api_key"] = default_api_key

        self.default_provider_config = self._clean_config(base_default)

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        provider_config: Optional[Dict[str, Any]] = None,
        *,
        outcome: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Translate ``text``. When ``outcome`` (a dict) is supplied, it is
        populated with ``used_fallback`` and ``credential_rejected`` so a
        caller can surface the exact 1H.8.2 user-facing message — without
        changing the return type for existing callers that don't pass it."""

        text = text or ""
        if not text.strip():
            return text

        if outcome is not None:
            outcome.setdefault("used_fallback", False)
            outcome.setdefault("credential_rejected", False)

        primary_config = self._clean_config(provider_config)
        default_config = self.default_provider_config

        attempts: list[tuple[str, Dict[str, Any], str]] = []
        if primary_config:
            attempts.append(
                ("primary", primary_config, primary_config.get("provider", ""))
            )
        if default_config and (
            not attempts or not self._configs_equivalent(default_config, attempts[0][1])
        ):
            attempts.append(
                ("default", default_config, default_config.get("provider", ""))
            )

        if not attempts:
            logger.warning(
                "Translation request skipped because no API URL is configured; returning original text."
            )
            return text

        for index, (label, attempt_config, provider_id) in enumerate(attempts):
            descriptor = self._describe_provider(attempt_config, provider_id)
            try:
                translated = self._perform_translation(
                    text=text,
                    source_lang=source_lang or "auto",
                    target_lang=target_lang,
                    provider_config=attempt_config,
                )
            except TranslationProviderError as exc:
                if outcome is not None and exc.status_code in (401, 403):
                    outcome["credential_rejected"] = True
                if label == "primary" and len(attempts) > index + 1:
                    fallback_desc = self._describe_provider(
                        attempts[index + 1][1], attempts[index + 1][2]
                    )
                    logger.warning(
                        "Primary translation provider (%s) failed: %s. Falling back to system provider (%s).",
                        descriptor,
                        exc,
                        fallback_desc,
                    )
                else:
                    logger.error(
                        "Translation provider (%s) failed: %s", descriptor, exc
                    )
                continue

            if label == "default" and attempts[0][0] == "primary":
                logger.info(
                    "System translation provider (%s) succeeded after fallback.",
                    descriptor,
                )
                if outcome is not None:
                    outcome["used_fallback"] = True
            return translated

        return text

    def _perform_translation(
        self,
        *,
        text: str,
        source_lang: str,
        target_lang: str,
        provider_config: Dict[str, Any],
    ) -> str:
        api_url = provider_config.get("api_url")
        api_key = provider_config.get("api_key")
        provider_id = provider_config.get("provider", "")
        headers = self._merge_headers(provider_config)
        self._apply_api_key(headers, api_key, provider_id, api_url)

        if not api_url:
            raise TranslationProviderError("missing_api_url")

        if self._should_use_chat_completion(api_url, provider_id):
            return self._translate_via_chat_completion(
                text=text,
                source_lang=source_lang,
                target_lang=target_lang,
                api_url=api_url,
                headers=headers,
                model=provider_config.get("model"),
                provider_id=provider_id,
                provider_config=provider_config,
            )

        payload = {
            "q": text,
            "source": source_lang or "auto",
            "target": target_lang,
            "format": "text",
        }
        if provider_config.get("model"):
            payload["model"] = provider_config["model"]

        try:
            response = requests.post(
                api_url, json=payload, headers=headers, timeout=self.timeout_s
            )
        except requests.RequestException as exc:
            raise TranslationProviderError(str(exc)) from exc

        if response.status_code != 200:
            raise TranslationProviderError(
                f"HTTP {response.status_code}", status_code=response.status_code
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise TranslationProviderError("invalid_json") from exc

        translated = self._extract_translated_text(data)
        if translated is None:
            raise TranslationProviderError("missing_translated_text")
        return translated

    def _clean_config(
        self, provider_config: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        cleaned: Dict[str, Any] = {}
        if not provider_config or not isinstance(provider_config, dict):
            return cleaned

        api_url = provider_config.get("api_url") or provider_config.get("url")
        if isinstance(api_url, str) and api_url.strip():
            cleaned["api_url"] = api_url.strip()

        api_key = provider_config.get("api_key") or provider_config.get("key")
        if isinstance(api_key, str) and api_key.strip():
            cleaned["api_key"] = api_key.strip()

        provider = provider_config.get("provider") or provider_config.get("provider_id")
        if isinstance(provider, str) and provider.strip():
            cleaned["provider"] = provider.strip().lower()

        model = provider_config.get("model") or provider_config.get("model_name")
        if isinstance(model, str) and model.strip():
            cleaned["model"] = model.strip()

        prompt = provider_config.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            cleaned["prompt"] = prompt.strip()

        headers = provider_config.get("headers")
        if isinstance(headers, dict):
            sanitized_headers: Dict[str, str] = {}
            for key, value in headers.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    continue
                cleaned_key = key.strip()
                cleaned_value = value.strip()
                if cleaned_key and cleaned_value:
                    sanitized_headers[cleaned_key] = cleaned_value
            if sanitized_headers:
                cleaned["headers"] = sanitized_headers

        return cleaned

    def _configs_equivalent(self, a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        comparable_keys = ("api_url", "api_key", "model", "provider")
        for key in comparable_keys:
            if (a.get(key) or "") != (b.get(key) or ""):
                return False
        return True

    def _describe_provider(self, config: Dict[str, Any], provider_id: str) -> str:
        if provider_id:
            return provider_id
        api_url = config.get("api_url")
        if api_url:
            return api_url
        return "custom"

    def _merge_headers(
        self, provider_config: Optional[Dict[str, Any]]
    ) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}

        if not provider_config or not isinstance(provider_config, dict):
            return headers

        maybe_headers = provider_config.get("headers")
        if isinstance(maybe_headers, dict):
            for key, value in maybe_headers.items():
                if value is None:
                    continue
                if not isinstance(key, str):
                    continue
                if not isinstance(value, str):
                    continue
                cleaned_key = key.strip()
                cleaned_value = value.strip()
                if not cleaned_key or not cleaned_value:
                    continue
                headers[cleaned_key] = cleaned_value
        return headers

    def _apply_api_key(
        self,
        headers: Dict[str, str],
        api_key: Optional[str],
        provider_id: str,
        api_url: Optional[str],
    ) -> None:
        if not api_key:
            return

        lowered = {k.lower(): k for k in headers}

        api_url_lower = api_url.lower() if isinstance(api_url, str) else ""

        if (
            provider_id.startswith("google_gemini")
            or "generatecontent" in api_url_lower
        ):
            if "x-goog-api-key" not in lowered:
                headers["X-Goog-Api-Key"] = api_key
            return

        if "authorization" not in lowered:
            headers["Authorization"] = f"Bearer {api_key}"  # standard convention

    def _should_use_chat_completion(
        self, api_url: Optional[str], provider_id: str
    ) -> bool:
        if provider_id in {
            "openai_gpt_3_5",
            "openrouter_free",
            "deepseek_chat",
            "qwen_plus",
            "google_gemini",
        }:
            return True
        if not api_url:
            return False
        lowered = api_url.lower()
        return "chat/completions" in lowered or "generatecontent" in lowered

    def _translate_via_chat_completion(
        self,
        *,
        text: str,
        source_lang: str,
        target_lang: str,
        api_url: str,
        headers: Dict[str, str],
        model: Optional[str],
        provider_id: str,
        provider_config: Dict[str, Any],
    ) -> str:
        gemini = self._is_gemini(provider_id, api_url)
        # Gemini names the model in the URL path; everything else needs it in the body.
        if not model and not gemini:
            raise TranslationProviderError("model_required")

        prompt_override = provider_config.get("prompt")
        prompt = prompt_override or (
            "Translate the following text from {source} to {target} and return only the translation."
        ).format(source=source_lang or "auto", target=target_lang)

        payload = self._chat_request_payload(
            provider_id=provider_id,
            api_url=api_url,
            model=model,
            system_prompt=prompt,
            user_content=text,
        )

        try:
            response = requests.post(
                api_url, json=payload, headers=headers, timeout=self.timeout_s
            )
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise TranslationProviderError(
                str(exc), status_code=exc.response.status_code if exc.response is not None else None
            ) from exc
        except requests.RequestException as exc:
            raise TranslationProviderError(str(exc)) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise TranslationProviderError("invalid_json") from exc

        content = self._extract_chat_content(
            "google_gemini" if gemini else provider_id, data
        )
        if content is None:
            raise TranslationProviderError("unexpected_payload")
        return content.strip()

    def _extract_chat_content(self, provider_id: str, data: Any) -> Optional[str]:
        """Pull the assistant's text out of a chat-completion response.

        Shared by Stage A and Stage B so a provider that works for one works
        for the other.
        """

        if not isinstance(data, dict):
            return None

        if provider_id == "google_gemini":
            candidates = data.get("candidates")
            if isinstance(candidates, list) and candidates:
                content = candidates[0].get("content", {})
                parts = content.get("parts")
                if isinstance(parts, list) and parts:
                    text_part = parts[0].get("text")
                    if isinstance(text_part, str):
                        return text_part
            return None

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content

        return None

    # --- Stage B: the coherence pass ---------------------------------------

    def _is_gemini(self, provider_id: str, api_url: Optional[str]) -> bool:
        if provider_id == "google_gemini":
            return True
        return "generatecontent" in (api_url or "").lower()

    def _chat_capable_config(
        self, candidates: Sequence[Optional[Dict[str, Any]]]
    ) -> Optional[Dict[str, Any]]:
        """First candidate that can actually answer a chat-completion request.

        Stage B picks its provider here rather than inheriting Stage A's, so
        a plain-MT draft provider can never end up being handed a prompt it
        has no field for (F-12).
        """

        for candidate in candidates:
            cleaned = self._clean_config(candidate)
            api_url = cleaned.get("api_url")
            provider_id = cleaned.get("provider", "")
            if not api_url:
                continue
            if not self._should_use_chat_completion(api_url, provider_id):
                continue
            # Gemini names its model in the URL path; every other shape needs
            # it in the body, and _chat_request would fail without it.
            if not cleaned.get("model") and not self._is_gemini(provider_id, api_url):
                continue
            return cleaned
        return None

    def _chat_request_payload(
        self,
        *,
        provider_id: str,
        api_url: str,
        model: Optional[str],
        system_prompt: str,
        user_content: str,
    ) -> Dict[str, Any]:
        if self._is_gemini(provider_id, api_url):
            # Gemini's generateContent takes no system role and no model in
            # the body -- same shape submission_quality_gate already uses.
            return {
                "contents": [
                    {"parts": [{"text": f"{system_prompt}\n\n{user_content}"}]}
                ]
            }
        return {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0,
        }

    def _parse_coherence_response(
        self, content: Optional[str], expected_indices: Sequence[int]
    ) -> Optional[Dict[int, str]]:
        """Validate the model honoured the one-output-per-region contract.

        Anything else -- merged regions, an extra region, a dropped region,
        prose instead of JSON -- returns None, and the caller keeps the
        literal drafts. A partially-applied coherence pass would silently
        misalign text against bubbles, which is worse than no pass at all.
        """

        if not content:
            return None
        stripped = _CODE_FENCE.sub("", content.strip())
        try:
            parsed = json.loads(stripped)
        except (ValueError, TypeError):
            return None

        entries: Any = parsed
        if isinstance(parsed, dict):
            entries = parsed.get("regions")
        if not isinstance(entries, list):
            return None

        translations: Dict[int, str] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                return None
            raw_index = entry.get("index")
            if isinstance(raw_index, bool) or not isinstance(raw_index, (int, float)):
                return None
            index = int(raw_index)
            value = entry.get("translation")
            if value is None:
                value = entry.get("text")
            if not isinstance(value, str):
                return None
            if index in translations:  # a region answered twice
                return None
            translations[index] = value

        if set(translations) != set(expected_indices):
            return None
        return translations

    def coherence_pass(
        self,
        regions: Sequence[Dict[str, Any]],
        *,
        target_lang: str,
        glossary: Optional[Dict[str, str]] = None,
        previous_page_last_lines: Optional[Sequence[str]] = None,
        chapter_summary: Optional[str] = None,
        provider_config: Optional[Dict[str, Any]] = None,
        coherence_provider_config: Optional[Dict[str, Any]] = None,
        outcome: Optional[Dict[str, Any]] = None,
    ) -> Optional[List[str]]:
        """Rewrite one page's literal drafts as a coherent whole.

        ``regions`` is the page in reading order; each entry carries
        ``index``, ``reading_order``, ``region_type``, ``source_text`` and
        ``literal_translation``. Returns a list of the same length and order,
        or ``None`` when the pass could not run -- in which case the caller
        keeps Stage A's drafts unchanged.

        ``outcome``, when supplied, is populated with ``applied``, ``reason``
        and ``provider`` so a caller can disclose which text a reader is
        actually looking at.
        """

        if outcome is not None:
            outcome.setdefault("applied", False)
            outcome.setdefault("reason", None)
            outcome.setdefault("provider", None)

        def _fail(reason: str) -> None:
            if outcome is not None:
                outcome["reason"] = reason

        regions = list(regions or [])
        if not regions:
            _fail("no_regions")
            return None
        if len(regions) > MAX_COHERENCE_REGIONS:
            _fail("too_many_regions")
            return None

        # Empty in, empty out -- enforced here rather than trusted to the
        # model, and empty regions are not worth a token in the payload.
        translatable = [
            region for region in regions if str(region.get("source_text") or "").strip()
        ]
        if not translatable:
            _fail("no_translatable_regions")
            return None

        config = self._chat_capable_config(
            [coherence_provider_config, provider_config, self.default_provider_config]
        )
        if config is None:
            logger.warning(
                "Coherence pass skipped: no chat-completion-capable provider is "
                "configured, so the page keeps its literal per-region draft."
            )
            _fail("no_chat_provider")
            return None

        api_url = config["api_url"]
        provider_id = config.get("provider", "")
        headers = self._merge_headers(config)
        self._apply_api_key(headers, config.get("api_key"), provider_id, api_url)

        payload_regions = [
            {
                "index": region.get("index", position),
                "reading_order": region.get("reading_order", position),
                "region_type": region.get("region_type"),
                "source_text": region.get("source_text") or "",
                "literal_translation": region.get("literal_translation") or "",
            }
            for position, region in enumerate(translatable)
        ]
        graph_prompt = build_coherence_payload(
            target_lang=target_lang,
            regions=payload_regions,
            glossary=glossary,
            previous_page_last_lines=previous_page_last_lines,
            chapter_summary=chapter_summary,
        )

        try:
            response = requests.post(
                api_url,
                json=self._chat_request_payload(
                    provider_id=provider_id,
                    api_url=api_url,
                    model=config.get("model"),
                    system_prompt=COHERENCE_SYSTEM_PROMPT,
                    user_content=json.dumps(graph_prompt, ensure_ascii=False),
                ),
                headers=headers,
                timeout=self.coherence_timeout_s,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning(
                "Coherence pass failed against %s: %s. Keeping literal drafts.",
                self._describe_provider(config, provider_id),
                exc,
            )
            _fail("provider_error")
            return None

        expected = [entry["index"] for entry in payload_regions]
        translations = self._parse_coherence_response(
            self._extract_chat_content(provider_id, data), expected
        )
        if translations is None:
            logger.warning(
                "Coherence pass from %s did not honour the one-output-per-region "
                "contract. Keeping literal drafts.",
                self._describe_provider(config, provider_id),
            )
            _fail("contract_violated")
            return None

        results: List[str] = []
        payload_by_position = iter(payload_regions)
        refined_by_index = translations
        for region in regions:
            source = str(region.get("source_text") or "")
            if not source.strip():
                results.append("")
                continue
            entry = next(payload_by_position)
            refined = refined_by_index.get(entry["index"], "")
            # A blank result for a non-empty region would erase text the
            # reader already had; the literal draft is the safer floor.
            results.append(
                refined
                if refined.strip()
                else (region.get("literal_translation") or "")
            )

        if outcome is not None:
            outcome["applied"] = True
            outcome["reason"] = "ok"
            outcome["provider"] = provider_id or api_url
        return results

    def _extract_translated_text(self, data: Any) -> Optional[str]:
        if isinstance(data, str):
            return data

        if not isinstance(data, dict):
            return None

        translated = data.get("translatedText")
        if isinstance(translated, str):
            return translated

        if isinstance(translated, list) and translated:
            first = translated[0]
            if isinstance(first, str):
                return first

        data_field = data.get("data")
        if isinstance(data_field, list) and data_field:
            first = data_field[0]
            if isinstance(first, dict):
                candidate = first.get("translatedText")
                if isinstance(candidate, str):
                    return candidate

        translations_field = data.get("translations")
        if isinstance(translations_field, list) and translations_field:
            first = translations_field[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                candidate = first.get("text")
                if isinstance(candidate, str):
                    return candidate

        return None


__all__ = [
    "TranslationService",
    "TranslationProviderError",
    "build_coherence_payload",
    "COHERENCE_SYSTEM_PROMPT",
    "MAX_COHERENCE_REGIONS",
]
