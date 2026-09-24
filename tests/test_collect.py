import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.collect import build_race_id, parse_result, save_race

ROOT = Path(__file__).resolve().parent.parent
CACHED = ROOT / "data" / "raw" / "202644090211.html"


class TestRaceId(unittest.TestCase):
    def test_build_race_id(self):
        # 2026年9月2日 大井(場コード44) 11R
        self.assertEqual(build_race_id("2026-09-02", "大井", 11), "202644090211")
        self.assertEqual(build_race_id("2026-09-02", "大井", 1), "202644090201")

    def test_unknown_venue_raises(self):
        with self.assertRaises(ValueError):
            build_race_id("2026-09-02", "東京", 11)


@unittest.skipUnless(CACHED.exists(), "取得済みHTMLのキャッシュが必要")
class TestParseResult(unittest.TestCase):
    """実際に取得した大井11Rアフター5スター賞のHTMLでパースを検証する。"""

    @classmethod
    def setUpClass(cls):
        cls.data = parse_result(CACHED.read_text(encoding="utf-8"), "202644090211")

    def test_race_info(self):
        i = self.data.info
        self.assertEqual(i.name, "アフター5スター賞競走")
        self.assertEqual(i.date, "2026-09-02")
        self.assertEqual(i.venue, "大井")
        self.assertEqual(i.race_no, 11)
        self.assertEqual(i.post_time, "20:15")
        self.assertEqual(i.kyori, 1200)
        self.assertEqual(i.baba, "良")
        self.assertEqual(i.head_count, 16)

    def test_finishing_order(self):
        self.assertEqual(len(self.data.horses), 16)
        top3 = [(h["着順"], h["馬番"], h["馬名"]) for h in self.data.horses[:3]]
        self.assertEqual(top3, [("1", "3", "ティントレット"),
                                 ("2", "13", "ナスティウェザー"),
                                 ("3", "8", "マスターオブライフ")])

    def test_horse_detail_columns(self):
        winner = self.data.horses[0]
        self.assertEqual(winner["騎手"], "矢野貴之")
        self.assertEqual(winner["人気"], "1")
        self.assertEqual(winner["単勝オッズ"], "1.9")
        self.assertEqual(winner["上がり3F"], "36.3")
        self.assertEqual(winner["馬体重"], "494(-10)")  # 空白が詰めてあること

    def test_payouts(self):
        pay = {(p["券種"], p["組み合わせ"]): p["配当"] for p in self.data.payouts}
        self.assertEqual(pay[("単勝", "3")], "190")
        self.assertEqual(pay[("馬連", "3-13")], "4710")
        self.assertEqual(pay[("ワイド", "8-13")], "1560")   # 複数組のワイドが取れること
        self.assertEqual(pay[("3連複", "3-8-13")], "3420")
        self.assertEqual(len(self.data.payouts), 12)

    def test_corner_positions(self):
        corners = {c["コーナー"]: c["通過順"] for c in self.data.corners}
        self.assertIn("4コーナー", corners)
        # 括弧は横並びを表す。空白が入っていないこと
        self.assertTrue(corners["4コーナー"].startswith("2,6,5,3,12,(8,4)"))
        self.assertNotIn(" ", corners["4コーナー"])

    def test_saved_csv_is_readable_by_feedback(self):
        import tempfile
        from keiba.feedback import RaceResult, load_payouts
        with tempfile.TemporaryDirectory() as d:
            paths = save_race(self.data, Path(d))
            result = RaceResult.from_csv(paths["結果"])
            payouts = load_payouts(paths["配当"])
        self.assertEqual(result.umaban_to_chakujun[3], 1)
        self.assertEqual(result.umaban_to_chakujun[13], 2)
        umaren = next(p for p in payouts if p.kind == "馬連")
        self.assertEqual(umaren.combo, frozenset({3, 13}))
        self.assertEqual(umaren.amount, 4710)


if __name__ == "__main__":
    unittest.main()


CACHED_PAST = ROOT / "data" / "raw" / "202644090211_past.html"


@unittest.skipUnless(CACHED_PAST.exists(), "取得済み馬柱HTMLのキャッシュが必要")
class TestParseShutubaPast(unittest.TestCase):
    """馬柱ページから、確定結果には無い事前情報が取れることを検証する。"""

    @classmethod
    def setUpClass(cls):
        from datetime import date

        from keiba.collect import parse_shutuba_past
        cls.entries = parse_shutuba_past(
            CACHED_PAST.read_text(encoding="utf-8"), date(2026, 9, 2)
        )
        cls.by_umaban = {e["馬番"]: e for e in cls.entries}

    def test_all_horses_parsed(self):
        self.assertEqual(len(self.entries), 16)

    def test_odds_and_ninki_for_every_horse(self):
        # 上位人気は <span class="Odds_Ninki"> で囲まれ構造が変わるため、全頭で確認する
        missing = [e["馬番"] for e in self.entries if e.get("人気") is None]
        self.assertEqual(missing, [], f"人気が取れていない馬番: {missing}")

    def test_favorite_details(self):
        fav = next(e for e in self.entries if e["人気"] == 1)
        self.assertEqual(fav["馬名"], "ティントレット")
        self.assertEqual(fav["単勝オッズ"], 1.9)
        self.assertEqual(fav["脚質"], "先行")
        self.assertEqual(fav["血統父"], "ホッコータルマエ")

    def test_interval_is_computed_from_previous_race_date(self):
        fav = next(e for e in self.entries if e["人気"] == 1)
        self.assertEqual(fav["前走間隔日数"], 70)   # 前走 2026-06-24 → 当日 2026-09-02
        self.assertEqual(fav["前走開催場"], "浦和")
        self.assertEqual(fav["長期休養明け"], "")   # 180日以内

    def test_jra_transfer_flag(self):
        # 14番サンライズホークは前走が福島(中央)＝転入初戦にあたる
        hawk = self.by_umaban[14]
        self.assertEqual(hawk["前走開催場"], "福島")
        self.assertEqual(hawk["転入初戦"], "Y")
        self.assertEqual(hawk["直近3走JRA数"], 3)
        # 前走が地方の馬にはフラグが立たない
        fav = next(e for e in self.entries if e["人気"] == 1)
        self.assertEqual(fav["転入初戦"], "")

    def test_kyakushitsu_is_normalized(self):
        styles = {e.get("脚質") for e in self.entries if e.get("脚質")}
        self.assertTrue(styles <= {"逃げ", "先行", "差し", "追込"}, styles)


# 枠順確定前の登録馬段階（Waku番セルが空）で parse_shutuba_past が全馬を
# 弾いて0頭になる件のfixture。2026-09-26 中山9R(9頭)・10R(28頭)のキャッシュを
# 架空のrace_id（場コード44=実在しない）に付け替えて保存してある
PREVIEW_SMALL = ROOT / "data" / "raw" / "202644090926_past.html"   # 9頭・枠順未確定
PREVIEW_LARGE = ROOT / "data" / "raw" / "202644090927_past.html"   # 28頭・枠順未確定
CONFIRMED_AFTER_DRAW = ROOT / "data" / "raw" / "202644090922_past.html"  # 11頭・枠順確定後


@unittest.skipUnless(PREVIEW_SMALL.exists(), "取得済み登録馬HTMLのキャッシュが必要")
class TestParseShutubaPreview(unittest.TestCase):
    """枠順確定前の登録馬段階から、脚質・厩舎・血統を拾えることを検証する。

    枠順未確定だと <td class="Waku"></td> が空になり、parse_shutuba_past は
    採用条件（馬番がintであること）で全馬を弾いて0頭になる。この
    レグレッションと、parse_shutuba_preview が代わりに拾えることの
    両方を固定する（Horse01/Horse02のマッピングは血統父/馬名のままで
    変わらない点に注意——枠順未確定でもクラス名は同じ）。
    """

    @classmethod
    def setUpClass(cls):
        from datetime import date
        cls.html = PREVIEW_SMALL.read_text(encoding="utf-8")
        cls.race_date = date(2026, 9, 26)
        from keiba.collect import parse_shutuba_preview
        cls.entries = parse_shutuba_preview(cls.html, cls.race_date)

    def test_unconfirmed_page_gives_zero_via_past_parser(self):
        # 枠順未確定ページは parse_shutuba_past だと0頭になる（既知の挙動）。
        # これが変わったら、以下の代用ロジックの前提そのものが崩れる
        from keiba.collect import parse_shutuba_past
        self.assertEqual(parse_shutuba_past(self.html, self.race_date), [])

    def test_all_horses_parsed(self):
        self.assertEqual(len(self.entries), 9)

    def test_registration_numbers_are_unique_ints(self):
        nums = [e["登録番号"] for e in self.entries]
        self.assertEqual(len(nums), len(set(nums)))
        self.assertTrue(all(isinstance(n, int) for n in nums))

    def test_no_waku_or_umaban_columns(self):
        # 枠番・馬番はまだ確定していないので出さない（本番の馬番と混同しない）
        for e in self.entries:
            self.assertNotIn("馬番", e)
            self.assertNotIn("枠番", e)

    def test_horse_name_and_sire_and_trainer(self):
        by_name = {e["馬名"]: e for e in self.entries}
        horse = by_name["エイシンウルトラン"]
        self.assertEqual(horse["血統父"], "トランセンド")
        self.assertEqual(horse["厩舎"], "地方・村上正")
        self.assertEqual(horse["脚質"], "差し")

    def test_kyakushitsu_is_normalized(self):
        styles = {e.get("脚質") for e in self.entries if e.get("脚質")}
        self.assertTrue(styles <= {"逃げ", "先行", "差し", "追込"}, styles)

    def test_legend_row_excluded(self):
        # テンプレートの凡例行（Horse02="[馬記号] 馬名 [ブリンカー]"のような
        # プレースホルダ）が混ざらないこと
        names = [e.get("馬名") for e in self.entries]
        self.assertNotIn("[馬記号] 馬名 [ブリンカー]", names)


@unittest.skipUnless(PREVIEW_LARGE.exists(), "取得済み登録馬HTMLのキャッシュが必要")
class TestParseShutubaPreviewLargeField(unittest.TestCase):
    """頭数の多いレース（28頭登録）でも取りこぼしが無いことを確認する。"""

    @classmethod
    def setUpClass(cls):
        from datetime import date
        from keiba.collect import parse_shutuba_preview
        cls.entries = parse_shutuba_preview(
            PREVIEW_LARGE.read_text(encoding="utf-8"), date(2026, 9, 26)
        )

    def test_all_horses_parsed(self):
        self.assertEqual(len(self.entries), 28)

    def test_no_duplicate_names(self):
        names = [e["馬名"] for e in self.entries]
        self.assertEqual(len(names), len(set(names)))

    def test_trainer_present_for_every_horse(self):
        missing = [e["登録番号"] for e in self.entries if not e.get("厩舎")]
        self.assertEqual(missing, [], f"厩舎が取れていない登録番号: {missing}")


@unittest.skipUnless(CONFIRMED_AFTER_DRAW.exists(), "取得済み馬柱HTMLのキャッシュが必要")
class TestParseShutubaPastStillWorksAfterRefactor(unittest.TestCase):
    """_parse_horse_row への共通化（登録馬プレビュー追加時）で、確定後の
    parse_shutuba_past の挙動が変わっていないことを固定する。"""

    @classmethod
    def setUpClass(cls):
        from datetime import date
        from keiba.collect import parse_shutuba_past
        cls.entries = parse_shutuba_past(
            CONFIRMED_AFTER_DRAW.read_text(encoding="utf-8"), date(2026, 9, 22)
        )
        cls.by_umaban = {e["馬番"]: e for e in cls.entries}

    def test_all_horses_parsed(self):
        self.assertEqual(len(self.entries), 11)

    def test_umaban_and_wakuban_are_ints(self):
        for e in self.entries:
            self.assertIsInstance(e["馬番"], int)
            self.assertIsInstance(e["枠番"], int)

    def test_horse_name_and_sire(self):
        h = self.by_umaban[1]
        self.assertEqual(h["馬名"], "サムワンユーラヴド")
        self.assertEqual(h["血統父"], "ダノンキングリー")
        self.assertEqual(h["厩舎"], "美浦・大和田")
