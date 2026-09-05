"""GitHub Pages に出す静的サイトを組み立てる。

アメブロには外部投稿APIが無く、他社アフィリエイトも禁止されている。
一方このリポジトリには予想の元データと結果が両方あるので、**同じ場所から
サイトを出す**のがいちばん素直で、費用もかからない。

    python3 -m keiba.cli site config/20260905_中央.json --outdir docs

出力:
    docs/index.html          最新の開催日
    docs/d/YYYY-MM-DD.html   その日の保存版
    docs/.nojekyll           GitHub Pages の Jekyll 処理を止める

index には過去の開催日への一覧を出す。予想と結果が同じページに残るので、
「何をどう外したか」がそのまま記録になる。
"""
from __future__ import annotations

import csv
import json
import re
from itertools import combinations
from pathlib import Path

from .betting import make_betting_plan
from .boxes import build_options
from .expectation import Expectation
from .marks import assign_marks
from .measure import measure_of
from .models import load_horses
from .scoring import score_race
from .single import best_single

TEMPLATE = Path(__file__).resolve().parent / "templates" / "board.html"
DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
DATE8_RE = re.compile(r"(\d{4})(\d{2})(\d{2})")


def find_date(*texts: str | None) -> str | None:
    """「2026-09-05」でも「20260904_大井」でも日付を拾う。"""
    for t in texts:
        if not t:
            continue
        for rx in (DATE_RE, DATE8_RE):
            if m := rx.search(t):
                return "-".join(m.groups())
    return None


def find_venue(*texts: str | None) -> str:
    """設定に venue が無いことがあるので、見出しやファイル名からも探す。

    大井の設定は競馬場が1つなので race ごとの venue を持たない。
    ここで拾えないと結果CSVのファイル名と突き合わせられない。
    """
    from . import profile
    known = profile.NAR_VENUES | profile.JRA_VENUES
    for t in texts:
        if not t:
            continue
        for name in known:
            if name in t:
                return name
    return ""


def _result_dir(venue: str | None) -> Path:
    from . import profile
    return Path("data/collected" if profile.profile_for_venue(venue) == profile.NAR
                else "data/collected_jra")


def load_result(directory: Path, venue: str, race_no: str, date: str) -> dict | None:
    """確定着順と配当を読む。まだ無ければ None。"""
    # 設定は「9R」、収集ファイルは「09R」と桁が違う。両方で探す
    num = re.sub(r"\D", "", str(race_no))
    if not num:
        return None
    hits: list[Path] = []
    for form in (f"{int(num):02d}R", f"{int(num)}R"):
        hits = sorted(directory.glob(f"{date}_{venue}{form}_*_結果.csv"))
        if hits:
            break
    if not hits:
        return None
    res = hits[0]
    stem = res.name.replace("_結果.csv", "")
    rows = [r for r in csv.DictReader(open(res, encoding="utf-8-sig"))
            if (r.get("着順") or "").isdigit()]
    if len(rows) < 3:
        return None
    rows.sort(key=lambda r: int(r["着順"]))

    payouts: dict[str, dict[frozenset, int]] = {}
    pay = directory / f"{stem}_配当.csv"
    if pay.exists():
        for q in csv.DictReader(open(pay, encoding="utf-8-sig")):
            try:
                combo = frozenset(int(x) for x in q["組み合わせ"].split("-"))
                payouts.setdefault(q["券種"], {})[combo] = int(q["配当"])
            except ValueError:
                continue

    def num_or_none(v, cast):
        try:
            return cast(v)
        except (TypeError, ValueError):
            return None

    top = [{"chaku": int(r["着順"]), "umaban": int(r["馬番"]),
            "waku": num_or_none(r.get("枠番"), int), "name": r["馬名"],
            "ninki": num_or_none(r.get("人気"), int),
            "odds": num_or_none(r.get("単勝オッズ"), float)}
           for r in rows[:3]]
    return {"top": top, "payouts": payouts,
            "top2": frozenset(int(r["馬番"]) for r in rows[:2]),
            "top3": frozenset(int(r["馬番"]) for r in rows[:3])}


def build_payload(config: Path, records=None, race_date: str | None = None) -> dict:
    """設定JSONから、ページに埋める予想＋結果のデータを作る。"""
    cfg = json.loads(config.read_text(encoding="utf-8"))
    heading = cfg.get("heading", "")
    date = race_date or find_date(heading, config.stem)
    # 設定に venue が無い場合の受け皿（大井の設定は競馬場が1つなので持たない）
    fallback_venue = find_venue(cfg.get("venue"), heading, cfg.get("title"), config.stem)
    exp = Expectation()
    out: dict = {"heading": heading, "date": date, "races": []}

    for r in cfg["races"]:
        venue = r.get("venue") or fallback_venue
        horses = load_horses(r["entries"])
        scores = score_race(horses, None, kyori=r.get("kyori"), records=records,
                            as_of=date, venue=venue)
        marked = assign_marks(scores, baba=r.get("baba", "良"))
        fav = min((h for h in horses if h.ninki), key=lambda h: h.ninki, default=None)
        plan = make_betting_plan(marked, baba=r.get("baba", "良"),
                                 favorite_odds=fav.tansho_odds if fav else None)
        order = [x.score.horse.umaban for x in marked]
        top = marked[0].score.total_yoi if marked else 1.0
        pick = best_single(order, favorite_odds=plan.favorite_odds)

        # 印は上位8頭だけだが、スコアは全馬ぶん出す
        mark_by = {x.score.horse.umaban: x.mark for x in marked}
        rows = []
        for i, sc in enumerate(sorted(scores, key=lambda s: -s.total_yoi), start=1):
            h = sc.horse
            mm = measure_of(sc)
            win, place = exp.format(i)
            rows.append({
                "rank": i, "mark": mark_by.get(h.umaban, ""), "umaban": h.umaban,
                "waku": h.wakuban, "name": h.name, "ninki": h.ninki,
                "odds": h.tansho_odds, "kyaku": h.kyakushitsu,
                "score": round(sc.total_yoi, 1),
                "ratio": round(sc.total_yoi / top, 3) if top else 0.0,
                "win": win, "place": place,
                "measure": [{"label": c.label, "pts": round(c.points, 1),
                             "max": c.max_points} for c in mm.categories],
                "items": [{"label": it.label, "note": it.note}
                          for it in sc.all_items()
                          if it.scored and it.note and it.points][:4]})

        # 回収率・黒字確率は公開ページに載せない方針。データにも入れない
        recommended = ("ワイド", 3) if plan.wide else ("馬連", 4)
        boxes = [{"kind": o.kind, "width": o.width, "points": o.points,
                  "rec": o.recommended,
                  "combos": [f"{a}-{b}" for a, b in o.combos]}
                 for o in build_options(order, favorite_odds=plan.favorite_odds,
                                        recommended=recommended)
                 if o.width in (3, 4, 5, 6)]

        result = None
        res = load_result(_result_dir(venue), venue, r["race_no"], date) if date else None
        if res:
            rank_by = {x["umaban"]: x["rank"] for x in rows}
            for t in res["top"]:
                t["mark"] = mark_by.get(t["umaban"], "")
                t["rank"] = rank_by.get(t["umaban"])
            verdict = None
            rec = next((b for b in boxes if b["rec"]), None)
            if rec:
                table = res["payouts"].get(rec["kind"], {})
                got = []
                for c in rec["combos"]:
                    a, b = (int(x) for x in c.split("-"))
                    t = frozenset((a, b))
                    hit = (t <= res["top3"]) if rec["kind"] == "ワイド" else (t == res["top2"])
                    if hit:
                        got.append({"combo": c, "pay": table.get(t)})
                verdict = {"kind": rec["kind"], "width": rec["width"],
                           "points": rec["points"], "hits": got}
            wide = None
            if pick is not None and pick.recommended:
                a, b = (int(x) for x in pick.combo.split("-"))
                t = frozenset((a, b))
                wide = {"combo": pick.combo, "hit": bool(t <= res["top3"]),
                        "pay": res["payouts"].get("ワイド", {}).get(t)}
            result = {"top": res["top"], "buy": verdict, "wide": wide}

        out["races"].append({
            "venue": venue, "no": r["race_no"], "name": r["name"],
            "surface": r.get("surface", ""), "post": r.get("post_time", ""),
            "single": (None if pick is None else
                       {"combo": pick.combo, "label": pick.label,
                        "rec": pick.recommended}),
            "horses": rows, "boxes": boxes, "result": result})
    return out


def render(payload: dict, archive: list[str] | None = None) -> str:
    """テンプレートにデータを流し込む。"""
    tpl = TEMPLATE.read_text(encoding="utf-8")
    data = json.dumps(payload, ensure_ascii=False)
    # JSON の中の "</" がスクリプトを閉じてしまわないようにする
    data = data.replace("</", "<\\/")
    html = tpl.replace("__DATA__", data)
    if archive:
        links = "".join(
            f'<a href="d/{d}.html">{d}</a>' for d in sorted(archive, reverse=True))
        html = html.replace("__ARCHIVE__", links)
    return html.replace("__ARCHIVE__", "")


def write_site(payload: dict, outdir: Path) -> dict[str, Path]:
    """docs/ に書き出す。日付ページを残し、**index は常にいちばん新しい日**にする。

    古い日を後から作り直しても index が巻き戻らないよう、各日のデータを
    JSONで残し、index はその中の最新から組み立てる。
    """
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / ".nojekyll").write_text("", encoding="utf-8")
    days = outdir / "d"
    days.mkdir(exist_ok=True)
    store = outdir / "_data"
    store.mkdir(exist_ok=True)

    written: dict[str, Path] = {}
    date = payload.get("date")
    if date:
        (store / f"{date}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        p = days / f"{date}.html"
        p.write_text(render(payload), encoding="utf-8")
        written["day"] = p

    dates = sorted((q.stem for q in store.glob("*.json")), reverse=True)
    newest = payload
    if dates:
        newest = json.loads((store / f"{dates[0]}.json").read_text(encoding="utf-8"))
    archive = [d for d in dates if d != newest.get("date")]
    index = outdir / "index.html"
    index.write_text(render(newest, archive), encoding="utf-8")
    written["index"] = index
    return written
