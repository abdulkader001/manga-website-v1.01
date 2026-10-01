"""Local Tesseract invocation details that silently broke non-English OCR."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image

from backend_fastapi.app.services import ocr_service as ocr


def test_language_flag_comes_before_the_tsv_config(monkeypatch):
    """Arguments after the 'tsv' config name are read as more config files,
    so a trailing '-l kor' was ignored and every page was OCR'd as English."""

    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        Path(f"{cmd[2]}.tsv").write_text(
            "level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\tleft\\ttop\\twidth\\theight\\tconf\\ttext\\n"
        )
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(ocr.subprocess, "run", fake_run)
    svc = ocr.OCRService()
    svc._tesseract_tsv_raw_rows(Image.new("RGB", (10, 10), "white"), None, "kor+eng")
    cmd = seen["cmd"]
    assert cmd[cmd.index("-l") + 1] == "kor+eng"
    assert cmd.index("-l") < cmd.index("tsv")
    assert cmd[-1] == "tsv"


def _word(text, left, width=30, line=1, height=34):
    return {"text": text, "left": left, "width": width, "height": height, "line_num": line}


def test_korean_syllables_are_glued_but_real_spaces_kept():
    words = [
        _word("저", 440),
        _word("딴", 472),  # 2px gap: same word
        _word("벌", 440, line=2),
        _word("레", 472, line=2),
        _word("한테", 504, width=60, line=2),
        _word("밀리고", 440, width=90, line=3),
        _word("있다고?", 548, width=100, line=3),  # 18px gap: a real space
    ]
    assert ocr._join_words(words) == "저딴 벌레한테 밀리고 있다고?"


def test_latin_words_keep_their_spaces():
    words = [_word("I", 10, width=8), _word("won't", 22, width=50), _word("lose", 76, width=40)]
    assert ocr._join_words(words) == "I won't lose"


def test_language_hint_maps_to_traineddata():
    assert ocr.tesseract_lang_for("ko") == "kor+eng"
    assert ocr.tesseract_lang_for("auto").startswith("kor+jpn+chi_sim")
    assert ocr.tesseract_lang_for(None) is None
