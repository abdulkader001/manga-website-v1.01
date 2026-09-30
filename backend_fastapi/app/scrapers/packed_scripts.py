"""Decoders for chapter pages that hide their image list inside a script.

manhuagui.com (and its mobile / regional mirrors) ships the page-image list as
a Dean-Edwards "packer" script whose word table is LZString-compressed
(``'<base64>'.splic('|')``). Unpacking it yields
``SMH.imgData({"files": [...], "path": "...", "sl": {"e": .., "m": ".."}})``.

Pure Python (no JavaScript is executed) and dependency-free; the LZString
routine is the standard ``decompressFromBase64`` algorithm.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from bs4 import BeautifulSoup

_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
_LOOKUP = {ch: i for i, ch in enumerate(_B64)}


def lz_decompress_base64(data: str) -> Optional[str]:
    """LZString ``decompressFromBase64``. ``None`` when the input is corrupt."""

    if not data:
        return ""
    data = re.sub(r"[^A-Za-z0-9+/=]", "", data)
    length = len(data)
    reset = 32

    def value_at(index: int) -> int:
        return _LOOKUP.get(data[index], 0) if index < length else 0

    state = {"val": value_at(0), "pos": reset, "index": 1}

    def read_bits(count: int) -> int:
        bits, power = 0, 1
        for _ in range(count):
            resb = state["val"] & state["pos"]
            state["pos"] >>= 1
            if state["pos"] == 0:
                state["pos"] = reset
                state["val"] = value_at(state["index"])
                state["index"] += 1
            bits |= (1 if resb > 0 else 0) * power
            power <<= 1
        return bits

    dictionary: Dict[int, str] = {0: "0", 1: "1", 2: "2"}
    enlarge, dict_size, num_bits = 4, 4, 3

    first = read_bits(2)
    if first == 0:
        current = chr(read_bits(8))
    elif first == 1:
        current = chr(read_bits(16))
    else:
        return ""
    dictionary[3] = current
    previous = current
    out: List[str] = [current]

    while True:
        if state["index"] > length + 1:
            return None
        code = read_bits(num_bits)
        if code == 0:
            dictionary[dict_size] = chr(read_bits(8))
            dict_size += 1
            code = dict_size - 1
            enlarge -= 1
        elif code == 1:
            dictionary[dict_size] = chr(read_bits(16))
            dict_size += 1
            code = dict_size - 1
            enlarge -= 1
        elif code == 2:
            return "".join(out)
        if enlarge == 0:
            enlarge = 2**num_bits
            num_bits += 1
        if code in dictionary:
            entry = dictionary[code]
        elif code == dict_size:
            entry = previous + previous[0]
        else:
            return None
        out.append(entry)
        dictionary[dict_size] = previous + entry[0]
        dict_size += 1
        enlarge -= 1
        previous = entry
        if enlarge == 0:
            enlarge = 2**num_bits
            num_bits += 1


def _encode_word(number: int, base: int) -> str:
    head = "" if number < base else _encode_word(number // base, base)
    rest = number % base
    if rest > 35:
        return head + chr(rest + 29)
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    return head + digits[rest]


def unpack_packer(payload: str, base: int, count: int, words: List[str]) -> str:
    """Reverse the Dean-Edwards packer: swap each encoded token for its word."""

    table: Dict[str, str] = {}
    for index in range(count - 1, -1, -1):
        token = _encode_word(index, base)
        table[token] = words[index] if index < len(words) and words[index] else token
    return re.sub(r"\b\w+\b", lambda m: table.get(m.group(0), m.group(0)), payload)


_PACKED = re.compile(
    r"\}\(\s*'((?:[^'\\]|\\.)*)'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'((?:[^'\\]|\\.)*)'"
    r"\s*(?:\[\s*(?:'\\x73\\x70\\x6c\\x69\\x63'|\"splic\"|'splic')\s*\]\(\s*'\\x7c'\s*\)|\.splic\(\s*'\|'\s*\))",
    re.S,
)


def unpack_script(script: str) -> Optional[str]:
    """The plain text hidden inside one packed manhuagui script."""

    match = _PACKED.search(script)
    if not match:
        return None
    payload = match.group(1).replace("\\'", "'").replace("\\\\", "\\")
    base, count = int(match.group(2)), int(match.group(3))
    words_text = lz_decompress_base64(match.group(4))
    if words_text is None:
        return None
    return unpack_packer(payload, base, count, words_text.split("|"))


def _balanced_object(text: str, start: int) -> Optional[str]:
    depth, in_str, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def manhuagui_images(soup: BeautifulSoup, host: str = "https://i.hamreus.com") -> List[str]:
    """Page-image URLs of a manhuagui chapter page, in reading order."""

    for script in soup.find_all("script"):
        body = script.string or script.get_text() or ""
        if "splic" not in body and "\\x73\\x70\\x6c\\x69\\x63" not in body:
            continue
        plain = unpack_script(body)
        if not plain:
            continue
        marker = plain.find("imgData(")
        brace = plain.find("{", marker) if marker >= 0 else -1
        literal = _balanced_object(plain, brace) if brace >= 0 else None
        if not literal:
            continue
        try:
            data: Dict[str, Any] = json.loads(literal)
        except ValueError:
            continue
        files, path = data.get("files") or [], str(data.get("path") or "")
        sig = data.get("sl") or {}
        query = ""
        if sig.get("e") is not None and sig.get("m"):
            query = f"?e={sig['e']}&m={sig['m']}"
        return [f"{host}{quote(path)}{quote(str(name))}{query}" for name in files if name]
    return []
