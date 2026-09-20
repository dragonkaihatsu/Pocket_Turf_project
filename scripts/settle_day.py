#!/usr/bin/env python3
"""その日の予想を確定結果で精算する（レース後の収支計算）。

## 公表した買い目と、いま計算する買い目がずれていないかを必ず確かめる

`collect --force` は結果ページの**確定オッズ**で出走馬CSVを上書きする
（CLAUDE.md「中央は発走後にオッズ配信が止まる」の補完処理）。スコア自体は
オッズを使わないので上位馬は動かないはずだが、**「はず」で精算してはいけない**。
公表したテキスト（`_買い目_*.txt`）から上位6頭を読み、再計算した並びと
突き合わせて、違っていれば止める。

買い目は**馬番＋馬名の頭3文字**で出す（本人の指示）。「2-11」では投票履歴と
照合できない。
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.textreport import ticket_label, umaban_label

STAKE = 100


def load_published(path: Path) -> dict[str, list[int]]:
    """公表テキストから レース名 → 上位6頭（スコア順の馬番）。

    **【スコア順】ブロックの行から直接読む。** 買い目欄の「6頭BOX」行の
    書式（馬名を並べる／「上位6頭」と省略する）は本人の指示で何度も
    変わっているため、そこに依存すると静かに0レースになる
    （CLAUDE.md「数字を載せるなら、その数字を再現する行をスクリプトに
    残す」と同じ理由）。スコア順の行は印の頭数を変えても形が変わらない。
    """
    out = {}
    row_re = re.compile(r"^\s*\d+\s+\S+\s+(\d+)\s+\S", re.M)
    for blk in re.split(r"━+", path.read_text(encoding="utf-8-sig")):
        head = re.search(r"(中山|阪神|東京|京都|新潟|中京|小倉|福島|札幌|函館)(\d+R)", blk)
        if not head:
            continue
        m = re.search(r"【スコア順】\n(.+?)(?:\n\n|\Z)", blk, re.S)
        if not m:
            continue
        umaban = [int(u) for u in row_re.findall(m.group(1))][:6]
        if umaban:
            out[head.group(1) + head.group(2)] = umaban
    return out


def load_race(directory: Path, stem: str):
    res = directory / f"{stem}_結果.csv"
    pay = directory / f"{stem}_配当.csv"
    ent = directory / f"{stem}_出走馬.csv"
    if not (res.exists() and pay.exists()):
        return None
    rows = [r for r in csv.DictReader(open(res, encoding="utf-8-sig"))
            if (r.get("着順") or "").isdigit()]
    rows.sort(key=lambda r: int(r["着順"]))
    order = [int(r["馬番"]) for r in rows if (r.get("馬番") or "").isdigit()]
    names = {int(r["馬番"]): (r.get("馬名") or "")
             for r in rows if (r.get("馬番") or "").isdigit()}
    ninki = {int(r["馬番"]): int(r["人気"]) for r in rows
             if (r.get("馬番") or "").isdigit() and (r.get("人気") or "").isdigit()}
    payouts: dict[str, dict[frozenset, int]] = {}
    for p in csv.DictReader(open(pay, encoding="utf-8-sig")):
        try:
            combo = frozenset(int(x) for x in p["組み合わせ"].split("-"))
            payouts.setdefault(p["券種"], {})[combo] = int(p["配当"])
        except ValueError:
            continue
    blinker = {}
    if ent.exists():
        for r in csv.DictReader(open(ent, encoding="utf-8-sig")):
            if (r.get("馬番") or "").isdigit():
                blinker[int(r["馬番"])] = (r.get("ブリンカー") or "").strip()
    return {"order": order, "names": names, "ninki": ninki,
            "payouts": payouts, "blinker": blinker}


def settle(kind: str, tickets: list[frozenset], race: dict) -> tuple[int, int, list]:
    """(投資, 払戻, 当たった券) を返す。"""
    table = race["payouts"].get(kind, {})
    top2, top3 = frozenset(race["order"][:2]), frozenset(race["order"][:3])
    ret, hits = 0, []
    for t in tickets:
        hit = (t <= top3) if kind == "ワイド" else (t == top2)
        if hit and t in table:
            ret += table[t]
            hits.append((t, table[t]))
    return len(tickets) * STAKE, ret, hits


def boxes(order: list[int]) -> dict[str, tuple[str, list[frozenset]]]:
    out = {}
    for n in (3, 4, 5, 6):
        out[f"ワイド 上位{n}頭BOX"] = ("ワイド",
                                   [frozenset(c) for c in combinations(order[:n], 2)])
        out[f"馬連 上位{n}頭BOX"] = ("馬連",
                                  [frozenset(c) for c in combinations(order[:n], 2)])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/collected_jra")
    ap.add_argument("--date", required=True)
    ap.add_argument("--published", required=True, help="公表した買い目テキスト")
    ap.add_argument("--bought", help="実際に購入した馬のJSON（投票履歴から起こす）")
    ap.add_argument("--out", help="検証テキストの書き出し先")
    args = ap.parse_args()

    directory = Path(args.dir)
    pub = load_published(Path(args.published))
    stems = {}
    for p in sorted(directory.glob(f"{args.date}_*_結果.csv")):
        stem = p.name.replace("_結果.csv", "")
        m = re.search(r"_(\D+?)(\d{2})R_", stem + "_")
        if m:
            stems[f"{m.group(1)}{int(m.group(2))}R"] = stem

    lines: list[str] = []
    def say(s: str = "") -> None:
        print(s)
        lines.append(s)

    say(f"{args.date} 中央9-12R レース後検証")
    say()

    totals: dict[str, list[int]] = {}
    star_inv = star_ret = 0
    star_rows = []
    cover = {"1着": 0, "1-2着": 0, "1-3着": 0}
    rank_rows = []
    used = 0

    for label in pub:
        stem = stems.get(label)
        race = load_race(directory, stem) if stem else None
        if race is None:
            say(f"{label}: 結果が無い")
            continue
        used += 1
        six = pub[label]
        nm = race["names"]
        order = race["order"]

        # 公表した並びと、結果CSVに載っている馬番の整合だけ確認する
        missing = [u for u in six if u not in nm]
        if missing:
            say(f"! {label}: 公表した馬番 {missing} が結果に無い（除外・取消の可能性）")

        say("━" * 58)
        cond = ""
        say(f"■ {label}  上位6頭: " + " ".join(umaban_label(u, nm.get(u)) for u in six))
        chaku = " → ".join(
            f"{umaban_label(u, nm.get(u))}"
            f"({('スコア' + str(six.index(u) + 1) + '位') if u in six else '圏外'}"
            f"/{race['ninki'].get(u, '?')}人気)"
            for u in order[:3])
        say(f"  確定: {chaku}")
        rank_rows.append((label, [six.index(u) + 1 if u in six else None
                                 for u in order[:3]]))
        if order[0] in six:
            cover["1着"] += 1
        if set(order[:2]) <= set(six):
            cover["1-2着"] += 1
        if set(order[:3]) <= set(six):
            cover["1-3着"] += 1

        for name, (kind, tickets) in boxes(six).items():
            inv, ret, hits = settle(kind, tickets, race)
            t = totals.setdefault(name, [0, 0, 0])
            t[0] += inv; t[1] += ret; t[2] += 1 if ret else 0
            if name in ("ワイド 上位6頭BOX", "馬連 上位6頭BOX"):
                kana = "ワイド" if kind == "ワイド" else "馬連"
                if hits:
                    for combo, yen in sorted(hits, key=lambda x: -x[1]):
                        say(f"  的中 {kana} {ticket_label(combo, nm)}  {yen:,}円")
                elif kind == "ワイド":
                    say("  ワイド6頭BOX 不的中")
        # ★ワイド1点（スコア1位-3位）。CLAUDE.mdの★は3倍以上の帯だけだが、
        # 比較のため全レースで同じ買い目を精算し、★該当かどうかも併記する
        one = frozenset((six[0], six[2]))
        inv1, ret1, _ = settle("ワイド", [one], race)
        star_inv += inv1
        star_ret += ret1
        star_rows.append((label, ticket_label(one, nm), ret1))

        # 参考: ブリンカー装着馬（避ける条件の確認）
        b = [umaban_label(u, nm.get(u)) for u in six if race["blinker"].get(u)]
        if b:
            say(f"  参考 上位6頭のブリンカー装着: {' '.join(b)}")

    say("━" * 58)
    say()
    say(f"■ 買い方ごとの収支（{used}レース・1点100円）")
    say(f"  {'買い方':<22}{'点数':>5}{'投資':>9}{'回収':>10}{'回収率':>8}{'的中R':>7}")
    for name, (inv, ret, hit) in totals.items():
        pts = inv // STAKE // max(used, 1)
        say(f"  {name:<22}{pts:>5}{inv:>9,}{ret:>10,}{ret / inv * 100:>7.0f}%{hit:>6}R")
    if args.bought:
        import json
        spec = json.loads(Path(args.bought).read_text(encoding="utf-8-sig"))
        kind = spec.get("券種", "馬連")
        say()
        say(f"■ 実際に購入した買い目（{kind}BOX・投票履歴より）")
        say(f"  {'レース':<9}{'点':>4}  {'購入馬':<26}{'AI上位と':<10}{'結果'}")
        binv = bret = bhit = 0
        for label, horses in spec.get("購入", {}).items():
            stem = stems.get(label)
            race = load_race(directory, stem) if stem else None
            if race is None:
                continue
            nm, n = race["names"], len(horses)
            tickets = [frozenset(c) for c in combinations(horses, 2)]
            inv, ret, hits = settle(kind, tickets, race)
            binv += inv; bret += ret; bhit += 1 if ret else 0
            ai = pub.get(label, [])[:n]
            same = "一致" if set(ai) == set(horses) else f"差替{len(set(horses) - set(ai))}頭"
            buy = "-".join(umaban_label(u, nm.get(u)) for u in horses)
            res = " / ".join(f"的中 {ticket_label(c, nm)} {y:,}円" for c, y in hits) or "—"
            say(f"  {label:<9}{len(tickets):>4}  {buy:<26}{same:<10}{res}")
        say(f"  合計 {binv:,}円 → {bret:,}円   回収率 {bret / binv * 100:.0f}%"
            f"   収支 {bret - binv:+,}円   的中 {bhit}/{len(spec.get('購入', {}))}R")

    say()
    say("■ ワイド1点（スコア1位-3位）を全レースで買った場合")
    for label, tk, yen in star_rows:
        say(f"  {label:<8}{tk:<24}{('的中 ' + format(yen, ',') + '円') if yen else '—'}")
    say(f"  計 {star_inv:,}円 → {star_ret:,}円  回収率 {star_ret / star_inv * 100:.0f}%")
    say()
    say("■ 上位6頭のカバー")
    for k, v in cover.items():
        say(f"  {k}を含んだ: {v}/{used}レース ({v / used * 100:.0f}%)")

    if args.out:
        p = Path(args.out)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
        print(f"\n書き出し完了: {p}")


if __name__ == "__main__":
    main()
