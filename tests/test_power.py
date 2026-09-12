"""母数判定のテスト。撤回した事例を固定して、同じ誤りを繰り返さないようにする。"""
import unittest

from keiba.power import judge, min_detectable_diff, required_n, wilson


class TestPower(unittest.TestCase):
    def test_required_n_matches_documented_table(self):
        """CLAUDE.mdに載せた必要母数の表と一致すること。"""
        self.assertAlmostEqual(required_n(0.22, 0.03), 1538, delta=20)
        self.assertAlmostEqual(required_n(0.22, 0.05), 562, delta=10)
        self.assertAlmostEqual(required_n(0.22, 0.08), 224, delta=5)
        self.assertAlmostEqual(required_n(0.22, 0.15), 66, delta=3)

    def test_min_detectable_diff_is_inverse(self):
        for n in (65, 243, 404, 828, 2251):
            d = min_detectable_diff(n, 0.22)
            self.assertLessEqual(required_n(0.22, d), n + 1)

    def test_wilson_handles_zero(self):
        self.assertEqual(wilson(0, 0), (0.0, 0.0))
        lo, hi = wilson(0, 125)
        # 下限は0だが浮動小数の残差が出るため厳密比較はしない
        self.assertAlmostEqual(lo, 0.0, places=12)
        self.assertLess(hi, 0.05)

    def test_retracted_case_is_undecidable(self):
        """撤回した「新規装着×前走1-5着」は判定不能になること。

        複勝率40.0%(26/65) 対 対照32.0%(1624/5077)。差は8ptあるが
        n=65では15pt未満は見えないので、差を主張してはいけない。
        """
        v = judge("新規装着×前走1-5着", 26, 65, 1624, 5077)
        self.assertEqual(v.code, "判定不能")
        self.assertGreater(v.mdd, 0.10)
        self.assertFalse(v.ok)

    def test_blinker_overall_is_separated(self):
        """装着あり18.6%(419/2251) 対 なし22.0%(2656/12058) は差あり。"""
        v = judge("装着あり", 419, 2251, 2656, 12058)
        self.assertEqual(v.code, "差あり")
        self.assertTrue(v.ok)
        self.assertLess(v.diff, 0)

    def test_large_n_no_effect_is_sayanashi(self):
        """母数が十分で差が無いなら『差なし』（判定不能ではない）。"""
        v = judge("対照に近い大母数", 2200, 10000, 2656, 12058)
        self.assertEqual(v.code, "差なし")


if __name__ == "__main__":
    unittest.main()
