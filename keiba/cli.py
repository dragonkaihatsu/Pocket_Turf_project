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
from pathlib import Path

from .betting import make_betting_plan
from .daily import build_from_config
from .feedback import RaceResult, generate_feedback_report, load_payouts
from .marks import assign_marks
from .models import load_history, load_horses
from .pace import forecast_pace
from .report import generate_report
from .scoring import score_race


def _build_common(args) -> tuple:
    horses = load_horses(args.entries)
    history = load_history(args.history) if args.history else None
    scores = score_race(horses, history, kyori=args.kyori)
    marked = assign_marks(scores, baba=args.baba)
    return horses, history, scores, marked


def cmd_predict(args) -> None:
    horses, history, scores, marked = _build_common(args)
    pace = forecast_pace(horses)
    plan = make_betting_plan(marked, baba=args.baba)
    html_out = generate_report(args.race_name, scores, marked, pace, plan, args.baba)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_out, encoding="utf-8")
    print(f"書き出し完了: {out_path}")

    print("\n--- 印 ---")
    for m in marked:
        print(f"{m.mark} {m.score.horse.umaban:>2} {m.score.horse.name} "
              f"(良{m.score.total_yoi:.1f} / 重{m.score.total_omoi:.1f})")


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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="競馬予想システム（100点スコアリング）")
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("entries", help="出走馬CSV")
    common.add_argument("--history", help="過去10年データCSV（任意）")
    common.add_argument("--race-name", required=True, help="レース名")
    common.add_argument("--kyori", type=int, help="レース距離(m)。高齢馬補正の軽減判定に使用")
    common.add_argument("--baba", default="良", choices=["良", "稍重", "重", "不良"], help="当日馬場状態")
    common.add_argument("--output", required=True, help="出力HTMLパス")

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

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
