"""OCR service implementation decoupled from Flask."""

from __future__ import annotations

import io
import re
import structlog
import os
import subprocess
import tempfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from ..core.settings import settings
from PIL import Image, ImageOps, UnidentifiedImageError
from . import ocr_normalize

logger = structlog.get_logger("ocr_service")


def _asbool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


DEFAULT_ENGINE_ENV = os.getenv("DEFAULT_OCR_ENGINE")
DEFAULT_ENGINE_SETTING = settings.default_ocr_engine or "tesseract"
DEFAULT_ENGINE = (DEFAULT_ENGINE_ENV or DEFAULT_ENGINE_SETTING).strip().lower()

if os.getenv("OCR_MODE"):
    OCR_MODE = os.getenv("OCR_MODE", "local").strip().lower()
else:
    if DEFAULT_ENGINE in {"", "none", "tesseract", "tesseract_local"}:
        OCR_MODE = "local"
    else:
        OCR_MODE = "remote"
REMOTE_OCR_URL = os.getenv("REMOTE_OCR_URL", "")

MAX_FILE_BYTES = int(os.getenv("OCR_SERVICE_MAX_FILE_BYTES", str(10 * 1024 * 1024)))
TESSERACT_CMD = os.getenv("OCR_SERVICE_TESSERACT_CMD", "tesseract")
DEFAULT_TESSERACT_PSM = str(os.getenv("OCR_SERVICE_DEFAULT_PSM", "6"))
REQUEST_TIMEOUT = int(os.getenv("OCR_SERVICE_TIMEOUT", "60"))

SHRINK_FOR_ACCURACY = _asbool(os.getenv("OCR_SHRINK_IMAGES", "true"), True)
OCR_MAX_DIM = int(os.getenv("OCR_MAX_DIM", "1600"))
DEFAULT_LANGS = os.getenv("OCR_LANGS", "eng")

# ISO language of the series -> Tesseract traineddata. English is added so
# SFX/lettering in Latin script inside the page is still picked up.
TESSERACT_LANGS = {
    "au": "kor+jpn+chi_sim+eng",  # "auto": text language not set on the series
    "ko": "kor+eng",
    "ja": "jpn+jpn_vert+eng",
    "zh": "chi_sim+chi_tra+eng",
    "en": "eng",
}


_CJK_CHAR = re.compile(r"[\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u3400-\u9fff\uac00-\ud7af\uf900-\ufaff]")


def _join_words(words: List[Dict[str, Any]]) -> str:
    """Rebuild a paragraph from Tesseract word rows.

    Tesseract reports Korean/Chinese/Japanese text syllable by syllable, so a
    plain space-join turns "저딴" into "저 딴". Neighbours on the same line
    whose facing characters are CJK and whose gap is small (a fraction of
    the glyph height) are glued; real word spaces are much wider.
    """

    out = ""
    prev = None
    for word in words:
        text = str(word.get("text") or "").strip()
        if not text:
            continue
        if prev is not None:
            same_line = prev.get("line_num") == word.get("line_num")
            gap = word.get("left", 0) - (prev.get("left", 0) + prev.get("width", 0))
            height = max(1, min(prev.get("height", 0) or 1, word.get("height", 0) or 1))
            glue = (
                same_line
                and _CJK_CHAR.match(text[0])
                and _CJK_CHAR.match(out[-1:] or " ")
                and gap < 0.35 * height
            )
            out += "" if glue else " "
        out += text
        prev = word
    return out.strip()


def tesseract_lang_for(language_hint: Optional[str]) -> Optional[str]:
    if not language_hint:
        return None
    return TESSERACT_LANGS.get(language_hint.strip().lower()[:2])

ALLOWED_FORMATS = {"PNG", "JPEG", "JPG"}


class OCRServiceError(Exception):
    pass


class OCRServiceValidationError(OCRServiceError):
    pass


class OCRServiceEngineError(OCRServiceError):
    pass


class OCRService:
    """OCR extraction service supporting local Tesseract or remote APIs."""

    def __init__(self) -> None:
        self.remote_url = REMOTE_OCR_URL or None
        self.max_file_bytes = MAX_FILE_BYTES
        self.tesseract_cmd = TESSERACT_CMD
        self.default_psm = DEFAULT_TESSERACT_PSM
        self.timeout = REQUEST_TIMEOUT
        self.default_langs = DEFAULT_LANGS
        self.available = True
        self.disabled_reason: Optional[str] = None
        self._local_checked = False
        self.local_enabled = False
        self.system_provider_config: Optional[Dict[str, Any]] = None

    def _disable_ocr(self, reason: str, exc: Optional[Exception] = None) -> None:
        if self.disabled_reason:
            return
        self.available = False
        self.disabled_reason = reason
        logger.warning("⚠️ OCR translation features disabled: %s", reason, exc_info=exc)

    def update_system_config(
        self,
        provider_config: Optional[Dict[str, Any]],
        *,
        local_enabled: bool,
        local_engine: Optional[str] = None,
    ) -> None:
        self.system_provider_config = dict(provider_config) if provider_config else None
        self.local_enabled = bool(local_enabled)
        if local_engine and isinstance(local_engine, str) and local_engine.strip():
            self.tesseract_cmd = local_engine.strip()
        else:
            self.tesseract_cmd = TESSERACT_CMD
        self._local_checked = False
        if self.system_provider_config and "api_url" in self.system_provider_config:
            self.remote_url = (
                self.system_provider_config.get("api_url") or self.remote_url
            )
        elif not self.system_provider_config:
            self.remote_url = REMOTE_OCR_URL or None

    def _initialize_local_ocr(self) -> None:
        try:
            self._check_tesseract()
        except OCRServiceEngineError as exc:  # pragma: no cover - env specific
            raise OCRServiceEngineError(
                "Local OCR requires Tesseract. Please install it and ensure "
                f"'{self.tesseract_cmd}' is available on the PATH."
            ) from exc

    def _initialize_remote_ocr(self) -> None:
        if not self.remote_url:
            raise OCRServiceEngineError("Remote OCR URL not configured")

    def _ensure_local_ready(self) -> None:
        if not self.local_enabled:
            raise OCRServiceEngineError("Local OCR is disabled by system configuration")
        if not self._local_checked:
            self._check_tesseract()
            self._local_checked = True

    def _resolve_provider(
        self, provider_config: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        config = provider_config or self.system_provider_config or {}
        if not isinstance(config, dict):
            config = {}

        provider_id_raw = config.get("provider") or config.get("provider_id")
        provider_id = (
            provider_id_raw.strip().lower() if isinstance(provider_id_raw, str) else ""
        )

        if provider_id in {"tesseract_local", "local"}:
            self._ensure_local_ready()
            return {"mode": "local", "config": config}

        remote_url = (
            config.get("api_url") if isinstance(config.get("api_url"), str) else None
        )
        api_key = (
            config.get("api_key") if isinstance(config.get("api_key"), str) else None
        )
        headers = (
            config.get("headers") if isinstance(config.get("headers"), dict) else None
        )

        if remote_url:
            return {
                "mode": "remote",
                "config": {
                    "provider": provider_id or "custom",
                    "api_url": remote_url,
                    "api_key": api_key,
                    "headers": headers,
                },
            }

        if self.remote_url:
            return {
                "mode": "remote",
                "config": {
                    "provider": provider_id or "system",
                    "api_url": self.remote_url,
                    "api_key": api_key,
                    "headers": headers,
                },
            }

        if self.local_enabled:
            self._ensure_local_ready()
            return {"mode": "local", "config": config}

        raise OCRServiceEngineError("No OCR provider configured")

    def _validate_image_data(self, image_data: bytes) -> Image.Image:
        if not image_data:
            raise OCRServiceValidationError("No image data provided.")
        if len(image_data) > self.max_file_bytes:
            raise OCRServiceValidationError(
                f"Image too large ({len(image_data)} bytes). Max allowed is {self.max_file_bytes} bytes."
            )
        try:
            img = Image.open(io.BytesIO(image_data))
            fmt = (img.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                raise OCRServiceValidationError(
                    f"Unsupported format: {fmt or 'unknown'}"
                )
            return img
        except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise OCRServiceValidationError(f"Invalid image: {exc}") from exc

    def _prepare_image(self, img: Image.Image) -> Image.Image:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        if SHRINK_FOR_ACCURACY:
            width, height = img.size
            if max(width, height) > OCR_MAX_DIM:
                scale = OCR_MAX_DIM / float(max(width, height))
                new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
                img = img.resize(new_size, Image.LANCZOS)
                logger.debug("OCR: shrunk image to %s", new_size)
        return img

    def _check_tesseract(self) -> None:
        try:
            subprocess.run(
                [self.tesseract_cmd, "--version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            logger.info("OCR: Local Tesseract found at '%s'", self.tesseract_cmd)
        except Exception as exc:
            raise OCRServiceEngineError(
                f"Tesseract not found or failed when running '{self.tesseract_cmd} --version': {exc}"
            ) from exc

    def _save_png_temp(self, img: Image.Image) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        path = Path(tmp.name)
        img.save(str(path), "PNG")
        return path

    def _tesseract_tsv_raw_rows(
        self, img: Image.Image, psm: Optional[str], lang: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Run Tesseract and return every parsed TSV word-row, all columns
        included (block_num/par_num/line_num/word_num alongside the usual
        text/left/top/width/height/conf). Shared by ``_run_tesseract_tsv``
        (word-level, unchanged) and ``_run_tesseract_regions`` (block/
        paragraph-level grouping for the 2B.6 normalized shape)."""

        psm_to_use = str(psm or self.default_psm)
        lang_to_use = (lang or self.default_langs).strip()

        png_path = self._save_png_temp(img)
        with tempfile.TemporaryDirectory() as tmpdir:
            tsv_out = Path(tmpdir) / "ocr_out"
            cmd = [
                self.tesseract_cmd,
                str(png_path),
                str(tsv_out),
                "--psm",
                psm_to_use,
                "--oem",
                "1",
            ]
            # Options must come before the config name: Tesseract reads every
            # argument after "tsv" as another config file, so a trailing
            # "-l kor" was silently ignored and every page was read as English.
            if lang_to_use:
                cmd.extend(["-l", lang_to_use])
            cmd.append("tsv")
            try:
                subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    check=True,
                    timeout=self.timeout,
                )
            except subprocess.CalledProcessError as exc:
                stderr = exc.stderr.decode("utf-8", "ignore") if exc.stderr else ""
                raise OCRServiceEngineError(
                    f"Tesseract failed: {stderr.strip()}"
                ) from exc
            finally:
                try:
                    png_path.unlink()
                except OSError:
                    pass

            tsv_file = Path(f"{tsv_out}.tsv")
            if not tsv_file.exists():
                raise OCRServiceEngineError("Tesseract did not produce TSV output")
            rows = tsv_file.read_text(encoding="utf-8").splitlines()

        headers = rows[0].split("\t") if rows else []
        parsed: List[Dict[str, Any]] = []
        for row in rows[1:]:
            columns = row.split("\t")
            if len(columns) != len(headers):
                continue
            data = dict(zip(headers, columns))
            text = data.get("text", "").strip()
            try:
                conf = float(data.get("conf", "0") or "0")
            except ValueError:
                conf = 0.0
            if not text:
                continue
            if conf < -10:
                continue
            try:
                left = int(data.get("left", "0") or 0)
                top = int(data.get("top", "0") or 0)
                width = int(data.get("width", "0") or 0)
                height = int(data.get("height", "0") or 0)
                block_num = int(data.get("block_num", "0") or 0)
                par_num = int(data.get("par_num", "0") or 0)
                line_num = int(data.get("line_num", "0") or 0)
                word_num = int(data.get("word_num", "0") or 0)
            except ValueError:
                continue
            parsed.append(
                {
                    "text": text,
                    "conf": conf,
                    "left": left,
                    "top": top,
                    "width": width,
                    "height": height,
                    "block_num": block_num,
                    "par_num": par_num,
                    "line_num": line_num,
                    "word_num": word_num,
                }
            )
        return parsed

    def _run_tesseract_tsv(
        self, img: Image.Image, psm: Optional[str], lang: Optional[str]
    ) -> List[Dict[str, Any]]:
        rows = self._tesseract_tsv_raw_rows(img, psm, lang)
        return [
            {
                "text": row["text"],
                "left": row["left"],
                "top": row["top"],
                "width": row["width"],
                "height": row["height"],
            }
            for row in rows
        ]

    def _run_tesseract_regions(
        self, img: Image.Image, psm: Optional[str], lang: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Group word-level TSV rows into one region per (block, paragraph)
        -- the closest Tesseract equivalent to "one region per bubble" that
        2B.6 expects, rather than 2B.6 regions collapsing to one per word."""

        rows = self._tesseract_tsv_raw_rows(img, psm, lang)
        groups: "OrderedDict[tuple, List[Dict[str, Any]]]" = OrderedDict()
        for row in rows:
            key = (row["block_num"], row["par_num"])
            groups.setdefault(key, []).append(row)

        regions: List[Dict[str, Any]] = []
        for words in groups.values():
            words_sorted = sorted(words, key=lambda w: (w["line_num"], w["word_num"]))
            text = _join_words(words_sorted)
            if not text:
                continue
            left = min(w["left"] for w in words)
            top = min(w["top"] for w in words)
            right = max(w["left"] + w["width"] for w in words)
            bottom = max(w["top"] + w["height"] for w in words)
            avg_conf = sum(w["conf"] for w in words) / len(words)
            regions.append(
                {
                    "text": text,
                    "left": left,
                    "top": top,
                    "width": right - left,
                    "height": bottom - top,
                    "confidence": avg_conf,
                }
            )
        return regions

    def _extract_local(
        self, image_data: bytes, psm: Optional[str], lang: Optional[str]
    ) -> Dict[str, Any]:
        self._ensure_available()
        self._ensure_local_ready()
        img = self._validate_image_data(image_data)
        prepared = self._prepare_image(img)
        items = self._run_tesseract_tsv(prepared, psm, lang)
        return {"items": items}

    def _extract_remote(
        self,
        image_data: bytes,
        psm: Optional[str],
        lang: Optional[str],
        provider_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        self._ensure_available()
        cfg = provider_config or {}
        url = cfg.get("api_url") if isinstance(cfg.get("api_url"), str) else None
        url = url or self.remote_url
        if not url:
            raise OCRServiceEngineError("Remote OCR URL not configured")

        headers: Dict[str, str] = {}
        raw_headers = (
            cfg.get("headers") if isinstance(cfg.get("headers"), dict) else None
        )
        if raw_headers:
            for key, value in raw_headers.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    continue
                cleaned_key = key.strip()
                if not cleaned_key:
                    continue
                headers[cleaned_key] = value.strip()

        api_key = cfg.get("api_key") if isinstance(cfg.get("api_key"), str) else None
        if api_key:
            lowered = {k.lower(): k for k in headers}
            if "authorization" not in lowered:
                headers["Authorization"] = f"Bearer {api_key}"

        files = {"file": ("image.png", image_data, "image/png")}
        data = {"language": lang or self.default_langs}
        if psm:
            data["psm"] = psm
        provider = cfg.get("provider") if isinstance(cfg.get("provider"), str) else None
        if provider:
            data["provider"] = provider
        response = requests.post(
            url,
            files=files,
            data=data,
            headers=headers or None,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _ensure_available(self) -> None:
        if not self.available:
            raise OCRServiceEngineError(
                self.disabled_reason or "OCR service unavailable"
            )

    def extract(
        self,
        image_data: bytes,
        psm: Optional[str] = None,
        lang: Optional[str] = None,
        *,
        provider_config: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        provider = self._resolve_provider(provider_config)
        if provider["mode"] == "remote":
            return self._extract_remote(image_data, psm, lang, provider.get("config"))
        return self._extract_local(image_data, psm, lang)

    def extract_file(
        self,
        file_like,
        psm: Optional[str] = None,
        lang: Optional[str] = None,
        *,
        provider_config: Optional[Dict[str, Any]] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        image_data = file_like.read()
        return self.extract(
            image_data, psm=psm, lang=lang, provider_config=provider_config
        )

    def extract_normalized(
        self,
        image_data: bytes,
        psm: Optional[str] = None,
        lang: Optional[str] = None,
        *,
        provider_config: Optional[Dict[str, Any]] = None,
        language_hint: Optional[str] = None,
        **_: Any,
    ) -> Dict[str, Any]:
        """The 2B.6 normalized shape, whichever engine actually ran (2B.6:
        "the frontend must be unable to determine which engine produced a
        result")."""

        provider = self._resolve_provider(provider_config)
        cfg = provider.get("config")
        provider_id = cfg.get("provider") if isinstance(cfg, dict) else None

        if provider["mode"] == "remote":
            raw = self._extract_remote(image_data, psm, lang, cfg)
            raw_items = raw.get("items", []) if isinstance(raw, dict) else []
            page = raw.get("page") if isinstance(raw, dict) else None
            if (
                not isinstance(page, dict)
                or not page.get("width")
                or not page.get("height")
            ):
                try:
                    probe = self._validate_image_data(image_data)
                    page = {"width": probe.width, "height": probe.height}
                except OCRServiceError:
                    page = page if isinstance(page, dict) else {}
            raw_regions = [
                {
                    "text": item.get("text"),
                    "x": item.get("left", item.get("x")),
                    "y": item.get("top", item.get("y")),
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "confidence": item.get("confidence", item.get("conf")),
                }
                for item in raw_items
                if isinstance(item, dict)
            ]
            image = None
        else:
            self._ensure_available()
            self._ensure_local_ready()
            img = self._validate_image_data(image_data)
            prepared = self._prepare_image(img)
            tess_regions = self._run_tesseract_regions(
                prepared, psm, lang or tesseract_lang_for(language_hint)
            )
            raw_regions = [
                {
                    "text": r["text"],
                    "x": r["left"],
                    "y": r["top"],
                    "width": r["width"],
                    "height": r["height"],
                    "confidence": r["confidence"],
                }
                for r in tess_regions
            ]
            page = {"width": prepared.width, "height": prepared.height}
            image = prepared
            provider_id = provider_id or "tesseract_local"

        return ocr_normalize.build_normalized_output(
            raw_regions,
            page=page,
            provider_id=provider_id,
            language_hint=language_hint,
            image=image,
        )

    def probe_local(self) -> bool:
        try:
            self._ensure_local_ready()
        except OCRServiceEngineError:
            return False
        return True


__all__ = [
    "OCRService",
    "OCRServiceError",
    "OCRServiceValidationError",
    "OCRServiceEngineError",
]
