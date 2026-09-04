"""コマンドラインエントリポイント。

使い方:
    python -m keiba.cli predict \\
        data/サンプル_出走馬.csv --history data/サンプル_過去10年.csv \\
        --race-name "サンプルS" --kyori 2000 --baba 良 \\
        --output output/サンプルS.html

    python -m keiba.cli feedback \\
        data/サンプル_出走馬.csv --history data/サンプル_過去10年.csv \\
        --race-name "サンプルS" --kyori 2000 --baba 良 \\
        --results data/サンプル_結果.csv --payouts data/サンプル_配当.csv \\
        --output output/サンプルS_フィードバック.html
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .betting import make_betting_plan
from .boxes import build_options
from .collect import (JRA_VENUE_CODES, VENUE_CODES, collect_day,
                      collect_jra_day, collect_jra_month, collect_month)
from .course import analyze, load_corpus
from .course import format_report as format_course_report
from . import profile
from .daily import build_from_config
from .expectation import Expectation
from .feedback import RaceResult, generate_feedback_report, load_payouts
from .horsedb import collect_horses, horse_ids_from_cache
from .horsedb import load_records as load_horse_records
from .horsedb import rebuild_from_cache
from .marks import assign_marks
from .models import load_history, load_horses
from .pace import forecast_pace
from .report import generate_report
from .scoring import score_race
from .stats import aggregate, format_report, load_records


def _load_horse_records(path: str | None = None) -> dict[str, list[dict]] | None:
    """馬別戦績を 馬名→行 の形で読む。無ければ None（コース適性は中立になる）。"""
    by_id = load_horse_records(path)
    if not by_id:
        return None
    by_name: dict[str, list[dict]] = {}
    for rows in by_id.values():
        if rows and rows[0]["馬名"]:
            by_name.setdefault(rows[0]["馬名"], []).extend(rows)
    for rows in by_name.values():
        rows.sort(key=lambda r: r["日付"])
    return by_name


def _build_common(args) -> tuple:
    horses = load_horses(args.entries)
    history = load_history(args.history) if args.history else None
    records = _load_horse_records(getattr(args, "records", None))
    as_of = getattr(args, "race_date", None)
    scores = score_race(horses, history, kyori=args.kyori,
                        records=records, as_of=as_of)
    if records is not None:
        hit = sum(1 for h in horses if h.name in records)
        print(f"馬別戦績: {hit}/{len(horses)}頭に実績データあり"
              f"（未取得の馬はコース適性・距離適性が中立値になります）")
    marked = assign_marks(scores, baba=args.baba)
    return horses, history, scores, marked


def cmd_predict(args) -> None:
    horses, history, scores, marked = _build_common(args)
    pace = forecast_pace(horses)
    plan = make_betting_plan(marked, baba=args.baba)
    html_out = generate_report(args.race_name, scores, marked, pace, plan, args.baba,
                               Expectation())

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_out, encoding="utf-8")
    print(f"書き出し完了: {out_path}")

    print("\n--- 印 ---")
    exp = Expectation()
    for rank, m in enumerate(marked, start=1):
        win_pct, place_pct = exp.format(rank)
        print(f"{m.mark} {m.score.horse.umaban:>2} {m.score.horse.name} "
              f"(良{m.score.total_yoi:.1f} / 重{m.score.total_omoi:.1f}) "
              f"1着{win_pct} / 着内{place_pct}")

    # 印が付かなかった馬も順位つきで出す。買い目に入れるかは買う人が決める
    marked_umaban = {m.score.horse.umaban for m in marked}
    rest = [s for s in sorted(scores, key=lambda s: s.total_yoi, reverse=True)
            if s.horse.umaban not in marked_umaban]
    if rest:
        print("\n--- 参考（印なし・スコア順） ---")
        for rank, sc_ in enumerate(rest, start=len(marked) + 1):
            win_pct, place_pct = exp.format(rank)
            print(f"{rank:>2}位 {sc_.horse.umaban:>2} {sc_.horse.name} "
                  f"(良{sc_.total_yoi:.1f}) 1着{win_pct} / 着内{place_pct}")

    print(f"\n{exp.source_note}")

    order = [m.score.horse.umaban for m in marked]
    fav_odds = plan.favorite_odds
    rec = ("ワイド", 3) if plan.wide else ("馬連", 4)
    print("\n--- 点数別の買い目候補（実測つき。広げるかは買う人の判断） ---")
    for o in build_options(order, favorite_odds=fav_odds, recommended=rec):
        head = "★推奨" if o.recommended else "    "
        print(f"{head} {o.label:<22} {'-'.join(str(u) for u in o.umaban)}")
        print(f"       {o.stat_text()}")


def cmd_feedback(args) -> None:
    horses, history, scores, marked = _build_common(args)
    plan = make_betting_plan(marked, baba=args.baba)
    result = RaceResult.from_csv(args.results)
    payouts = load_payouts(args.payouts) if args.payouts else []

    html_out = generate_feedback_report(args.race_name, marked, plan, result, payouts)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_out, encoding="utf-8")
    print(f"書き出し完了: {out_path}")


def cmd_daily(args) -> None:
    html_out = build_from_config(args.config)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_out, encoding="utf-8")
    print(f"書き出し完了: {out_path}")


def cmd_stats(args) -> None:
    paths = args.configs or sorted(Path("config").glob("*.json"))
    if not paths:
        print("設定JSONが見つかりません（config/*.json）")
        return
    records, skipped = load_records(paths)
    agg = aggregate(records)
    print(format_report(agg, skipped))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nJSON書き出し: {out}")


def cmd_collect(args) -> None:
    if "-" in args.races:
        lo, hi = args.races.split("-")
        numbers = list(range(int(lo), int(hi) + 1))
    else:
        numbers = [int(x) for x in args.races.split(",")]

    if not (args.date or args.month):
        print("--date か --month のどちらかを指定してください")
        return

    # 中央は race_id が開催回・日目で決まるため、日付から組み立てられない。
    # カレンダーとレース一覧を引く専用の経路に流す
    if args.venue in JRA_VENUE_CODES or args.venue == "中央":
        venue = None if args.venue == "中央" else args.venue
        if args.month:
            year, month = (int(x) for x in args.month.split("-"))
            print(f"{args.month} の中央（{args.venue}）のレース結果を取得します")
            collected = collect_jra_month(
                year=year, month=month, venue=venue, race_numbers=numbers,
                outdir=Path(args.outdir), cache_dir=Path(args.cache_dir),
                interval=args.interval, force=args.force,
            )
        else:
            print(f"{args.date} 中央（{args.venue}）のレース結果を取得します")
            collected = collect_jra_day(
                date=args.date, venue=venue, race_numbers=numbers,
                outdir=Path(args.outdir), cache_dir=Path(args.cache_dir),
                interval=args.interval, force=args.force,
            )
        print(f"\n取得完了: {len(collected)}レース → {args.outdir}")
        return

    if args.month:
        year, month = (int(x) for x in args.month.split("-"))
        print(f"{args.month} の{args.venue}のレース結果を取得します")
        collected = collect_month(
            year=year, month=month, venue=args.venue, race_numbers=numbers,
            outdir=Path(args.outdir), cache_dir=Path(args.cache_dir),
            interval=args.interval, force=args.force,
        )
    else:
        print(f"{args.date} {args.venue} のレース結果を取得します（{len(numbers)}レース）")
        collected = collect_day(
            date=args.date, venue=args.venue, race_numbers=numbers,
            outdir=Path(args.outdir), cache_dir=Path(args.cache_dir),
            interval=args.interval, force=args.force,
        )
    print(f"\n取得完了: {len(collected)}レース → {args.outdir}")


def cmd_horses(args) -> None:
    if args.rebuild:
        out = Path(args.out) if args.out else profile.active().path("horse_records.csv")
        rebuild_from_cache(Path(args.horse_cache), out)
        return
    ids = horse_ids_from_cache(Path(args.cache_dir))
    if not ids:
        print(f"{args.cache_dir} に馬柱HTMLのキャッシュがありません"
              "（先に collect を実行してください）")
        return
    print(f"馬柱キャッシュから {len(ids)}頭 の馬IDを取得しました")
    out = Path(args.out) if args.out else profile.active().path("horse_records.csv")
    collect_horses(ids, outpath=out, cache_dir=Path(args.horse_cache),
                   interval=args.interval, limit=args.limit)


def cmd_course(args) -> None:
    corpus = load_corpus(args.dir, kyori=args.kyori)
    if not len(corpus):
        print(f"{args.dir} に結果CSVが見つかりません（先に collect を実行してください）")
        return
    a = analyze(corpus)
    print(format_course_report(a))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON書き出し: {out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="競馬予想システム（100点スコアリング）")
    p.add_argument("--profile", choices=[profile.NAR, profile.JRA],
                   help="使う実測データ。省略時は競馬場名から自動判定し、"
                        "判定できなければ地方(nar)")
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("entries", help="出走馬CSV")
    common.add_argument("--history", help="過去10年データCSV（任意）")
    common.add_argument("--race-name", required=True, help="レース名")
    common.add_argument("--kyori", type=int, help="レース距離(m)。高齢馬補正の軽減判定に使用")
    common.add_argument("--baba", default="良", choices=["良", "稍重", "重", "不良"], help="当日馬場状態")
    common.add_argument("--output", required=True, help="出力HTMLパス")
    common.add_argument("--records", help="馬別戦績CSV（既定 data/horse_records.csv）")
    common.add_argument("--race-date", help="レース日 (YYYY-MM-DD)。指定するとその日より前の戦績だけを使う")

    p_predict = sub.add_parser("predict", parents=[common], help="スコアリング・買い目プランを出力")
    p_predict.set_defaults(func=cmd_predict)

    p_feedback = sub.add_parser("feedback", parents=[common], help="レース後フィードバックを出力")
    p_feedback.add_argument("--results", required=True, help="結果CSV（馬番,着順）")
    p_feedback.add_argument("--payouts", help="配当CSV（券種,組み合わせ,配当）")
    p_feedback.set_defaults(func=cmd_feedback)

    p_daily = sub.add_parser("daily", help="開催日単位のArtifact向けページを出力")
    p_daily.add_argument("config", help="開催日設定JSON")
    p_daily.add_argument("--output", required=True, help="出力HTMLパス")
    p_daily.set_defaults(func=cmd_daily)

    p_stats = sub.add_parser("stats", help="結果が判明したレースを横断して成績を集計")
    p_stats.add_argument("configs", nargs="*", help="開催日設定JSON（省略時は config/*.json）")
    p_stats.add_argument("--json", help="集計結果をJSONでも書き出す")
    p_stats.set_defaults(func=cmd_stats)

    p_collect = sub.add_parser("collect", help="レース結果・払戻・通過順を取得して保存")
    p_collect.add_argument("--date", help="開催日 (YYYY-MM-DD)")
    p_collect.add_argument("--month", help="対象月 (YYYY-MM)。その月の開催日を自動で調べて全日取得")
    p_collect.add_argument("--venue", required=True,
                           choices=sorted(VENUE_CODES) + sorted(JRA_VENUE_CODES) + ["中央"],
                           help="競馬場。中央の場名または「中央」（その日の全場）も指定できる")
    p_collect.add_argument("--races", default="1-12", help="レース番号 (例: 1-12 または 10,11,12)")
    p_collect.add_argument("--outdir", default="data/collected", help="CSV出力先")
    p_collect.add_argument("--cache-dir", default="data/raw", help="取得HTMLのキャッシュ先")
    p_collect.add_argument("--interval", type=float, default=1.5, help="リクエスト間隔(秒)")
    p_collect.add_argument("--force", action="store_true",
                           help="取得済みのレースも再取得する（既定はスキップ）")
    p_collect.set_defaults(func=cmd_collect)

    p_horses = sub.add_parser("horses", help="馬ごとの全戦績をnetkeibaから取得")
    p_horses.add_argument("--cache-dir", default="data/raw",
                          help="馬IDを拾う馬柱HTMLのキャッシュ先")
    p_horses.add_argument("--horse-cache", default="data/raw_horse",
                          help="馬別成績HTMLのキャッシュ先")
    p_horses.add_argument("--out", help="戦績CSVの出力先（既定はプロファイルの horse_records.csv）")
    p_horses.add_argument("--interval", type=float, default=1.5, help="リクエスト間隔(秒)")
    p_horses.add_argument("--limit", type=int, help="先頭N頭だけ取得（動作確認用）")
    p_horses.add_argument("--rebuild", action="store_true",
                          help="通信せずキャッシュ済みHTMLだけからCSVを作り直す")
    p_horses.set_defaults(func=cmd_horses)

    p_course = sub.add_parser("course", help="収集した結果からコース傾向を集計")
    p_course.add_argument("--dir", default="data/collected", help="収集済みCSVのディレクトリ")
    p_course.add_argument("--kyori", type=int, help="距離で絞る (例: 1200)")
    p_course.add_argument("--json", help="集計結果をJSONでも書き出す")
    p_course.set_defaults(func=cmd_course)

    return p


def resolve_profile(args) -> None:
    """使うプロファイルを決めて有効化する。

    明示指定 > 競馬場名からの自動判定 > 既定(地方) の順。中央のレースを
    地方の対応表で採点する取り違えを防ぐため、必ずここを通す。
    """
    if getattr(args, "profile", None):
        profile.use(args.profile)
    elif venue := getattr(args, "venue", None):
        profile.use_for_venue(venue)
    print(profile.active().describe())


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    resolve_profile(args)
    args.func(args)


if __name__ == "__main__":
    main()
