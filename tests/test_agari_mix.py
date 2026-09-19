"""基礎能力の味付け（持ち時計 ⇄ 上がり3F）を固定する。

2026-09-19 に本人の指示で入れた `agari_mix`。既定(0.0)は従来どおり
持ち時計優先で、**この既定を動かすと派生表4本の校正がまとめてずれる**
ので、既定が変わっていないことをここで固定する。
"""
import unittest

from keiba import scoring as sc
from keiba.models import Horse


def _horse(umaban: int, name: str, agari: float) -> Horse:
    return Horse(umaban=umaban, wakuban=1, name=name, sex_age="牡4",
                 kinryo=57.0, jockey="テスト", zenso_chakujun=3,
                 zenso_race="テストS", agari_3f=agari, chokyo_hyoka="")


class TestAgariMix(unittest.TestCase):
    def setUp(self):
        # 上がり3Fと持ち時計が**逆の順序**になるよう作る。
        # 混ぜたときに本当に両方が効いているかを見分けるため
        self.field = [_horse(1, "アカ", 33.0), _horse(2, "イロ", 35.0),
                      _horse(3, "ウミ", 36.0), _horse(4, "エダ", 37.0)]
        self.mochi = {"アカ": -1.0, "イロ": 0.0, "ウミ": 1.0, "エダ": 2.0}

    def _pts(self, name, mix):
        h = next(x for x in self.field if x.name == name)
        return sc.score_kiso_nouryoku(h, self.field, self.mochi, mix).points

    def test_default_is_mochidokei_only(self):
        """既定(0.0)は持ち時計だけを見る。上がり3F最速のアカが最下位になる"""
        self.assertEqual(self._pts("アカ", 0.0), sc.MAX_KISO * 0.4)
        self.assertEqual(self._pts("エダ", 0.0), sc.MAX_KISO)

    def test_mix_one_is_agari_only(self):
        """1.0は上がり3Fだけ。順序が入れ替わる"""
        self.assertEqual(self._pts("アカ", 1.0), sc.MAX_KISO)
        self.assertEqual(self._pts("エダ", 1.0), sc.MAX_KISO * 0.4)

    def test_blend_sits_between(self):
        for name in ("アカ", "イロ", "ウミ", "エダ"):
            lo, hi = sorted((self._pts(name, 0.0), self._pts(name, 1.0)))
            mid = self._pts(name, 0.5)
            self.assertGreaterEqual(mid, lo - 1e-9, name)
            self.assertLessEqual(mid, hi + 1e-9, name)

    def test_note_says_which_scale_was_used(self):
        """どの尺度で付いた点か、内訳から分かること（根拠を出せる状態にする）"""
        h = self.field[0]
        self.assertIn("持ち時計",
                      sc.score_kiso_nouryoku(h, self.field, self.mochi, 0.0).note)
        self.assertIn("上がり3F",
                      sc.score_kiso_nouryoku(h, self.field, self.mochi, 1.0).note)
        blended = sc.score_kiso_nouryoku(h, self.field, self.mochi, 0.5).note
        self.assertIn("持ち時計", blended)
        self.assertIn("上がり3F", blended)

    def test_no_mochidokei_means_mix_changes_nothing(self):
        """持ち時計が作れない馬は、どの味付けでも同じ点。
        混ぜる対象が無いのに値が動くと、情報のある馬だけ歪む"""
        for mix in (0.0, 0.5, 1.0):
            item = sc.score_kiso_nouryoku(self.field[0], self.field, None, mix)
            self.assertEqual(item.points,
                             sc.score_kiso_nouryoku(self.field[0], self.field,
                                                    None, 0.0).points)

    def test_override_wins_over_every_mix(self):
        h = _horse(9, "オテ", 34.0)
        h.kiso_nouryoku_override = 20.0
        for mix in (0.0, 0.5, 1.0):
            self.assertEqual(
                sc.score_kiso_nouryoku(h, self.field + [h], self.mochi, mix).points,
                20.0)

    def test_score_race_threads_the_weight(self):
        """score_race まで重みが届いていること。
        途中の呼び出しで落とすと**エラーは出ず、静かに既定へ戻る**
        （records/as_of/venue を渡し忘れて旧尺度で出ていた 2026-09-19 と同じ型）"""
        orig = sc.load_mochi
        sc.load_mochi = lambda *a, **k: dict(self.mochi)
        try:
            a = sc.score_race(self.field, None, agari_mix=0.0)
            b = sc.score_race(self.field, None, agari_mix=1.0)
        finally:
            sc.load_mochi = orig
        self.assertNotEqual([s.total_yoi for s in a], [s.total_yoi for s in b])


if __name__ == "__main__":
    unittest.main()
