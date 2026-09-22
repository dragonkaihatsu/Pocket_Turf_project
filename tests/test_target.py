"""予想の対象レース（障害・新馬を外す）を固定する。

本人の指示（2026-09-22）は「障害と新馬戦は除外する／**ただし結果は集積する**」
なので、**除外は予想・買い目だけで、収集は一切絞らない**。ここを緩めると
どちらの側も静かに壊れるので、両方をテストで押さえる:

  1. 障害の判定は `馬場種別`（surface）が権威で、レース名に頼らない
  2. 名前に「障害」が入らない障害戦（中山グランドジャンプ・新潟JS…）を
     取りこぼさない
  3. 逆に平地の WASJ・ヤングJSFR を障害と誤らない
  4. 4つの出力経路が `split_races` を通る（経路ごとに条件を書かない）
  5. `collect` は絞られていない
"""
import csv
import unittest
from pathlib import Path

from keiba.target import (excluded_note, excluded_reason, is_debut, is_jump,
                          is_target, race_class, split_races)

ROOT = Path(__file__).resolve().parent.parent
RACE_INFO = ROOT / "data/profiles/jra/race_info.csv"

# コーパスで実際に見つかった、名前に「障害」が入らない障害戦（45本の一部）
JUMP_NAMES_WITHOUT_SHOUGAI = (
    "中山グランドジャンプ", "中山グランドJ", "新潟JS", "東京ハイジャンプ",
    "東京HJ", "阪神スプリングジャンプ", "阪神スプリングJ", "京都ハイジャンプ",
    "牛若丸JS", "小倉SJ", "ペガサスJS", "春麗JS",
)
# 平地なのに JS/SJ/ジャンプ を含む名前（正規表現で拾うと16本が誤爆する）
FLAT_NAMES_THAT_LOOK_LIKE_JUMPS = (
    "WASJ第1戦", "WASJ第2戦", "WASJ第3戦", "WASJ第4戦",
    "ヤングJSFR中京第1戦", "ヤングJSFR中京第2戦",
)


class TestSurfaceIsAuthoritative(unittest.TestCase):
    """障害は surface で決める。名前は補助にしか使わない。"""

    def test_surface_decides_even_when_the_name_says_nothing(self):
        for name in JUMP_NAMES_WITHOUT_SHOUGAI:
            with self.subTest(name=name):
                # 名前だけでは分からない
                self.assertFalse(is_jump(name=name), name)
                # surface があれば確実に分かる
                self.assertTrue(is_jump(surface="障", name=name), name)
                self.assertTrue(is_jump(surface="障3200m", name=name), name)

    def test_flat_races_that_look_like_jumps_are_not_excluded(self):
        """WASJ・ヤングJSFR は平地。`JS`/`SJ` を拾うと16本を落とす。"""
        for name in FLAT_NAMES_THAT_LOOK_LIKE_JUMPS:
            with self.subTest(name=name):
                self.assertFalse(is_jump(surface="芝", name=name), name)
                self.assertTrue(is_target(name=name, surface="芝"), name)

    def test_the_word_shougai_alone_is_enough(self):
        """設定JSONに surface が無い経路でも、名前に入っていれば外す。"""
        self.assertTrue(is_jump(name="3歳以上障害未勝利"))
        self.assertEqual(excluded_reason(name="4歳以上障害オープン"), "障害")

    def test_flat_surfaces_are_targets(self):
        for s in ("芝", "ダ", "芝1600m", "ダ1200m", None, ""):
            with self.subTest(surface=s):
                self.assertFalse(is_jump(surface=s, name="鋸山特別"))


class TestDebut(unittest.TestCase):
    def test_debut_is_decided_by_name(self):
        self.assertTrue(is_debut("2歳新馬"))
        self.assertEqual(excluded_reason(name="2歳新馬", surface="芝"), "新馬")

    def test_未勝利_is_not_a_debut(self):
        self.assertFalse(is_debut("2歳未勝利"))
        self.assertTrue(is_target(name="2歳未勝利", surface="芝"))

    def test_jump_wins_when_both_apply(self):
        """理由は1つだけ返す。障害が先（入力の欠け方が重いほう）。"""
        self.assertEqual(excluded_reason(name="新馬", surface="障"), "障害")


class TestSplitAndNote(unittest.TestCase):
    SAMPLE = [
        {"name": "3歳以上障害未勝利", "surface": "障3000m"},
        {"name": "2歳新馬", "surface": "芝1600m"},
        {"name": "新潟JS", "surface": "障3250m"},      # 名前に障害が無い
        {"name": "WASJ第1戦", "surface": "芝1200m"},    # 平地。残す
        {"name": "鋸山特別", "surface": "芝1800m"},
    ]

    def test_split(self):
        kept, dropped = split_races(self.SAMPLE)
        self.assertEqual([r["name"] for r in kept], ["WASJ第1戦", "鋸山特別"])
        self.assertEqual([(r["name"], why) for r, why in dropped],
                         [("3歳以上障害未勝利", "障害"), ("2歳新馬", "新馬"),
                          ("新潟JS", "障害")])

    def test_note_counts_by_reason(self):
        _, dropped = split_races(self.SAMPLE)
        self.assertEqual(excluded_note(dropped), "対象外 3レース（障害2・新馬1）")

    def test_note_is_empty_when_nothing_is_dropped(self):
        """該当が無ければ行そのものを出さない（参考注記と同じ扱い）。"""
        self.assertEqual(excluded_note([]), "")

    def test_split_keeps_the_original_dicts(self):
        kept, _ = split_races(self.SAMPLE)
        self.assertIs(kept[-1], self.SAMPLE[-1])


class TestRaceClass(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(race_class("新潟JS", "障3250m"), "障害")
        self.assertEqual(race_class("2歳新馬", "芝"), "新馬")
        self.assertEqual(race_class("3歳未勝利", "ダ"), "未勝利")
        self.assertEqual(race_class("3歳以上1勝クラス", "芝"), "条件(1-3勝)")
        self.assertEqual(race_class("鋸山特別", "芝"), "固有名(特別〜G1)")


class TestCorpus(unittest.TestCase):
    """コーパスで、名前による判定が実際に両方向へ外すことを示す。"""

    @classmethod
    def setUpClass(cls):
        if not RACE_INFO.exists():
            raise unittest.SkipTest(f"{RACE_INFO} が無い")
        with open(RACE_INFO, encoding="utf-8-sig") as f:
            cls.rows = list(csv.DictReader(f))

    def test_jump_races_exist_and_names_are_unreliable(self):
        jump = [r for r in self.rows
                if (r.get("馬場種別") or "").strip().startswith("障")]
        self.assertGreater(len(jump), 300, "障害が数百本あるはず")
        noname = [r for r in jump if "障害" not in r["stem"]]
        # 14%が名前で拾えない。だから surface を権威にしている
        self.assertGreater(len(noname), 30,
                           "名前に障害が入らない障害戦が相当数あるはず")
        for r in noname:
            with self.subTest(stem=r["stem"]):
                self.assertTrue(is_jump(surface=r["馬場種別"]))

    def test_surface_column_name(self):
        """列名は `馬場種別`。変わったら判定が全部 False に倒れる。"""
        self.assertIn("馬場種別", self.rows[0])


class TestCollectionIsNotNarrowed(unittest.TestCase):
    """**結果は集積する。** 収集側が除外を参照していないことを固定する。"""

    def test_collect_does_not_import_target(self):
        src = (ROOT / "keiba/collect.py").read_text(encoding="utf-8")
        self.assertNotIn("target", src,
                         "収集は絞らない（本人の指示『ただし、結果は集積します』）")

    def test_verification_is_not_narrowed(self):
        """検証（`keiba/stats.py`・`scripts/settle_day.py`）は全レースを見る。

        `score_race` を呼ぶ経路は5本あるが、除外を通すのは**予想の4本だけ**。
        検証まで絞ると、外したレースの結果が記録から消えてしまう。
        """
        for name in ("keiba/stats.py", "scripts/settle_day.py"):
            with self.subTest(path=name):
                src = (ROOT / name).read_text(encoding="utf-8")
                self.assertNotIn("split_races", src,
                                 "結果は集積する（本人の指示）")

    def test_corpus_builders_do_not_import_target(self):
        for name in ("scripts/build_horse_records.py",
                     "scripts/build_mochidokei.py",
                     "scripts/build_ratings.py",
                     "scripts/build_race_info.py"):
            with self.subTest(script=name):
                src = (ROOT / name).read_text(encoding="utf-8")
                self.assertNotIn("from keiba.target", src)


class TestAllOutputPathsShareTheDecision(unittest.TestCase):
    """4つの出力経路が `keiba/target.py` を通る。経路ごとに条件を書かない。"""

    PATHS = ("keiba/cli.py", "keiba/shinbun.py", "keiba/kompi.py",
             "keiba/daily.py")

    def test_every_output_path_imports_split_races(self):
        for name in self.PATHS:
            with self.subTest(path=name):
                src = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("from .target import", src)
                self.assertIn("split_races(", src)

    def test_every_output_path_has_an_escape_hatch(self):
        """`include_all` で元に戻せる（外した判断を検証し直せるように）。"""
        for name in self.PATHS:
            with self.subTest(path=name):
                src = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("include_all", src)


class TestOutputPathsActuallyRun(unittest.TestCase):
    """4経路を**実際に動かす**。

    `tests/test_same_score.py` はソースの文字列しか見ないので、
    fef2370 で `keiba/daily.py` に入った `load_by_name` の import 漏れを
    3日間捕まえられなかった（`keiba.cli daily` は毎回 NameError で落ちていた）。
    除外を通した以上、**通した先が動くこと**まで見る。
    """

    CONFIG = ROOT / "config/2026-09-22_中央.json"

    @classmethod
    def setUpClass(cls):
        import json
        if not cls.CONFIG.exists():
            raise unittest.SkipTest(f"{cls.CONFIG} が無い")
        with open(cls.CONFIG, encoding="utf-8-sig") as f:
            cls.config = json.load(f)
        cls.kept, cls.dropped = split_races(cls.config["races"])
        if not cls.dropped:
            raise unittest.SkipTest("この設定には除外対象が無い")

    def test_shinbun(self):
        from keiba import shinbun
        page = shinbun.build_sheet(self.config)
        self.assertIn(excluded_note(self.dropped), page)
        full = shinbun.build_sheet(self.config, include_all=True)
        self.assertGreater(len(full), len(page), "--include-all で増えるはず")

    def test_kompi(self):
        from keiba.kompi import build_sheet
        page = build_sheet(self.config, None)
        full = build_sheet(self.config, None, include_all=True)
        self.assertGreater(len(full), len(page))

    def test_daily(self):
        from keiba.daily import build_daily_page
        page = build_daily_page(self.config)
        for r, _ in self.dropped:
            with self.subTest(race=r["name"]):
                self.assertNotIn(f'data-tab="{r["race_no"]}"', page)
        for r in self.kept:
            with self.subTest(race=r["name"]):
                self.assertIn(f'data-tab="{r["race_no"]}"', page)


if __name__ == "__main__":
    unittest.main()
