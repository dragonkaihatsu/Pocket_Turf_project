"""HTMLを画像（PNG）にする。

**同梱の chromium（`--headless`）はこの環境で文字を1つも描かない。**
背景とセルの罫線だけのPNGが出る（2026-09-14に実測）。同じフォルダにある
`headless_shell` では日本語まで正しく出るので、**そちらを先に探す**。
どちらも見つからなければ理由を添えて失敗する（黙って空の画像を作らない）。

高さは推測せず**ページに測らせる**。`--dump-dom` は読み込み後のDOMを
吐くので、寸法を属性へ書き込む小さなスクリプトを仕込めば読み取れる。
2回起動する（測る→撮る）が、1枚あたり数秒で済む。
"""
from __future__ import annotations

import glob
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

# 探す順。**headless_shell が先**（上記のとおり chromium は文字を描かない）
CANDIDATES = (
    "/opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell",
    "/opt/pw-browsers/chromium-*/chrome-linux/chrome",
    "/opt/pw-browsers/chromium",
)
COMMANDS = ("chromium", "chromium-browser", "google-chrome")

# 画像にするときだけ効かせる上書き。表は横スクロールの箱に入っているので、
# そのままだと**見えている分しか写らない**。画像では全列を出す
SHOT_CSS = """
html,body{margin:0;padding:0;background:#D8D2C2}
.shot{display:inline-block;padding:18px 16px}
.shot .kompi{max-width:none;width:max-content}
.shot .kompi .scroll{overflow:visible}
.shot .kompi table{width:auto}
"""
MEASURE = (
    "<script>(function(){var e=document.querySelector('.shot');"
    "document.body.setAttribute('data-kw',Math.ceil(e.offsetWidth));"
    "document.body.setAttribute('data-kh',Math.ceil(e.offsetHeight));})()</script>"
)
SIZE_RE = re.compile(r'data-kw="(\d+)"\s+data-kh="(\d+)"')


def find_chrome(env: str | None = None) -> str:
    if env:
        return env
    for pat in CANDIDATES:
        hit = sorted(glob.glob(pat))
        if hit:
            return hit[-1]
    for c in COMMANDS:
        p = shutil.which(c)
        if p:
            return p
    raise RuntimeError(
        "chromium が見つからないのでPNGを作れない。"
        "--chrome で実行ファイルを渡すか、HTMLだけを出力すること"
    )


def shot_page(sheet: str, fonts: str = "", measure: bool = False) -> str:
    """貼る用のHTML片を、画像にするための1枚の文書にする。"""
    return (
        "<!doctype html>\n<html lang=\"ja\"><head><meta charset=\"utf-8\">"
        f"{fonts}<style>{SHOT_CSS}</style></head>"
        f'<body><div class="shot">{sheet}</div>{MEASURE if measure else ""}'
        "</body></html>\n"
    )


def _run(chrome: str, page: Path, *args: str) -> subprocess.CompletedProcess:
    cmd = [chrome, "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
           "--virtual-time-budget=4000", *args, page.as_uri()]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=180)


def render_png(sheet: str, out: str | Path, fonts: str = "", scale: int = 2,
               chrome: str | None = None) -> tuple[int, int]:
    """PNGを書き出し、(幅, 高さ) をCSSピクセルで返す（画像は scale 倍）。"""
    exe = find_chrome(chrome)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "sheet.html"
        page.write_text(shot_page(sheet, fonts, measure=True), encoding="utf-8")
        dom = _run(exe, page, "--dump-dom").stdout
        m = SIZE_RE.search(dom)
        if not m:
            raise RuntimeError("ページの寸法を測れなかった（描画に失敗した可能性）")
        w, h = int(m.group(1)), int(m.group(2))
        _run(exe, page, f"--screenshot={out}",
             f"--window-size={w},{h}", f"--force-device-scale-factor={scale}")
    if not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"PNGを書き出せなかった: {out}")
    return w, h
