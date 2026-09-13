"""買い目に馬名の頭を付ける処理の固定テスト。

収支計算のとき「2-11」だけだと、どの馬を買ったのか馬柱を開き直さないと
分からない。「2テラメ-11ヨウシ」なら投票履歴や結果画面と直接突き合わせられる。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keiba.textreport import NAME_CHARS, ticket_label, umaban_label


class TestUmabanLabel(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(umaban_label(2, "テラメリタ"), "2テラメ")
        self.assertEqual(umaban_label(11, "ヨウシタンレイ"), "11ヨウシ")

    def test_default_is_three_chars(self):
        self.assertEqual(NAME_CHARS, 3)

    def test_short_name_is_not_padded(self):
        """3文字未満でも在るぶんだけ。詰め物をしない。"""
        self.assertEqual(umaban_label(5, "アカ"), "5アカ")

    def test_missing_name(self):
        """名前が無いときは馬番だけ。`?` のような作り物を出さない。"""
        self.assertEqual(umaban_label(7, None), "7")
        self.assertEqual(umaban_label(7, ""), "7")


class TestTicketLabel(unittest.TestCase):
    NAMES = {2: "テラメリタ", 11: "ヨウシタンレイ", 6: "ハギノアルデバラン"}

    def test_pair(self):
        self.assertEqual(ticket_label({2, 11}, self.NAMES), "2テラメ-11ヨウシ")

    def test_sorted_by_umaban(self):
        """集合で渡しても馬番の昇順で出る（並びが揺れると突き合わせにくい）。"""
        self.assertEqual(ticket_label({11, 2}, self.NAMES),
                         ticket_label({2, 11}, self.NAMES))

    def test_triple(self):
        self.assertEqual(ticket_label({2, 6, 11}, self.NAMES),
                         "2テラメ-6ハギノ-11ヨウシ")

    def test_unknown_horse_keeps_number(self):
        self.assertEqual(ticket_label({2, 99}, self.NAMES), "2テラメ-99")


if __name__ == "__main__":
    unittest.main()
