"""参考注記（表示のみ・スコアには入れない）。

CLAUDE.md の2段階のうち第1段階を、1か所にまとめる。**独立検証を通って
いない／通ったが点数化していない**材料を、買う人が見て判断できる形で
出す。判断は買う人に委ねるという方針そのもの。

含めるもの:

  相手関係     メンバー質の差分（`keiba/aite.py`）。前走着順との
               組み合わせだけが両期間で再現したので、そこだけ踏み込む
  騎手の得意条件 `jockey_stats.json` の14,706組み合わせから、**今日の条件に
               当たるもの**だけを引く。作ってあるのに予想で一度も使って
               いなかった
  中山の道悪×内枠 「配水管が整備されているので雨でも内が有利」という読みを
               全10場で測った結果、中山の芝だけが両期間で正（+6.9p/+4.9p）。
               ただし n=146・要る差9.7p で**判定不能**

## 出さないもの

血統×コース特性は独立検証で「差なし」（40セルでほぼ全部±1pt以内・
母数は十分）なので、表示もしない。判定不能と棄却は分けて扱う。

## 母数の扱い

騎手の条件は `信頼できる母数`（n≥10 かつ 勝利10本以上）のものだけ出す。
**表示するのは複勝率と母数**にした。単勝回収率は期間をまたいで一度も
再現していないので、100%超を「得意」の看板にしない。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import profile

# 中山・芝の稍重以上で内枠(1-2)がやや有利（scripts/ame_uchi.py）。
# 判定不能なので断定しない言い方にする
NAKAYAMA_WET_INSIDE = (
    "中山・芝の稍重以上は内枠(1-2)がやや有利に出ている"
    "（+6.0p・n=146／両期間で同じ向き・判定不能）"
)
# 同じ測定で、中山ダートは逆だった（良馬場の内枠が −3.9p・差あり）
NAKAYAMA_DIRT_INSIDE = (
    "中山・ダートは内枠(1-2)が不利に出ている（良馬場 −3.9p・差あり）"
)


def distance_band(kyori: int) -> str:
    """`scripts/jockey_stats.py` と同じ境目。**境目を2か所に書くと
    静かにずれる**ので、あちらはここを import する。"""
    if kyori <= 1400:
        return "短距離(~1400)"
    if kyori <= 1800:
        return "マイル(1401-1800)"
    if kyori <= 2200:
        return "中距離(1801-2200)"
    return "長距離(2201~)"


def waku_band(waku: int | None) -> str | None:
    if waku in (1, 2):
        return "内枠(1-2)"
    if waku in (7, 8):
        return "外枠(7-8)"
    if waku and 3 <= waku <= 6:
        return "中枠(3-6)"
    return None


def load_jockey_stats(path: Path | str | None = None,
                      venue: str | None = None) -> list[dict]:
    """騎手の条件別実測を読む。無ければ空。

    基準表と同じく**競馬場から**プロファイルを決める。`active()` に頼ると
    集計スクリプトがプロファイルを切り替えないまま地方の表を中央に当てる
    （CLAUDE.md「集計スクリプトがプロファイルを指定していない事故」）。
    """
    if path is None:
        prof = profile.for_venue(venue) if venue else profile.active()
        path = prof.path("jockey_stats.json")
    p = Path(path)
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8"))
    return [c for c in d.get("組み合わせ", []) if c.get("信頼できる母数")]


def _conditions(venue: str | None, surface: str | None, kyori: int | None,
                kyakushitsu: str | None, wakuban: int | None) -> set[str]:
    """今日のこのレース・この馬に当たる条件文字列の集合。"""
    band = distance_band(kyori) if kyori else None
    sd = surface[:1] if surface else None        # 「芝」/「ダ」
    out: set[str] = set()
    if venue:
        out.add(venue)
        if sd and band:
            out.add(f"{venue}/{sd}/{band}")
    if band:
        out.add(band)
        if sd:
            out.add(f"{band}/{sd}")
    if sd:
        out.add(sd)
    if kyakushitsu:
        out.add(kyakushitsu)
        if band:
            out.add(f"{kyakushitsu}/{band}")
        if sd:
            out.add(f"{kyakushitsu}/{sd}")
    if w := waku_band(wakuban):
        out.add(w)
    return out


def _resolve(jockey: str, names: set[str]) -> str | None:
    """騎手名を実測表の表記に寄せる。

    馬柱は略記で、表記ゆれもある（三浦／三浦皇）。`scoring._lookup` と同じ
    「完全一致 → 候補が1人に定まる前方一致」の順で引き、**2人以上に
    当たるなら None**。誰の成績か確定できないときは出さないのが正しい
    （前方一致で辞書順の先頭を返して別人を掴んだ不具合があった）。
    """
    if jockey in names:
        return jockey
    from .scoring import _candidates
    cand = _candidates({n: n for n in names}, jockey)
    return next(iter(cand)) if len(cand) == 1 else None


def jockey_note(jockey: str, stats: list[dict], venue: str | None,
                surface: str | None, kyori: int | None,
                kyakushitsu: str | None, wakuban: int | None,
                baseline: dict | None = None) -> str | None:
    """今日の条件が、その騎手にとって得意／苦手かを返す。

    **水準ではなく、その騎手の中での対比を出す。** 「丹内は差し/芝で
    複勝率24%」は得意条件ではなく単なる成績で、しかも水準は市場が
    織り込んでいる（コース特性で「その馬の中での対比」を出すのと同じ理由）。
    比べる相手はその騎手の全体複勝率（`ratings.json`）。

    差が**その母数で見える大きさ**を超えたときだけ出す。n=10の条件で
    3ptの差を「得意」と呼ぶと、母数が薄いときの大きな数字を拾う。
    """
    if not jockey or not stats:
        return None
    key = _resolve(jockey, {c["騎手"] for c in stats})
    if key is None:
        return None

    want = _conditions(venue, surface, kyori, kyakushitsu, wakuban)
    hit = [c for c in stats if c["騎手"] == key and c["条件"] in want]
    if not hit:
        return None

    base = None
    if baseline:
        from .scoring import _lookup
        if rec := _lookup(baseline, jockey):
            base = rec.get("複勝率")
    if base is None:
        return None

    from . import power
    scored = []
    for c in hit:
        diff = c["複勝率"] - base
        if abs(diff) >= power.min_detectable_diff(c["n"], base):
            scored.append((abs(diff), diff, c))
    if not scored:
        return None
    _, diff, c = max(scored)
    tag = "得意" if diff > 0 else "苦手"
    return (f"騎手={key} {c['条件']}が{tag}"
            f"（複勝率{c['複勝率']:.0%}→全体{base:.0%}・{c['n']}騎乗）")


def course_note(venue: str | None, surface: str | None,
                baba: str | None) -> str | None:
    """レース単位の参考注記（中山の道悪×内枠）。"""
    if venue != "中山" or not surface:
        return None
    if surface.startswith("芝") and baba and baba != "良":
        return NAKAYAMA_WET_INSIDE
    if surface.startswith("ダ"):
        return NAKAYAMA_DIRT_INSIDE
    return None
