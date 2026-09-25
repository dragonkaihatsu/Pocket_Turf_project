"""JRA馬場情報（クッション値・含水率）の読み取りを固定する。

JRAのページは中身を静的HTMLから読み込む作りで、場ごとに
`<div id="rcA" title="中山">` で区切られる。その形が変わったら
ここが落ちて気づけるようにする（黙って空を返すのがいちばん危ない）。
"""
import unittest

from keiba.babainfo import cushion_label, parse_cushion, parse_moist, summary_lines

CUSHION = '''<div id="cushion_data_list">
<div id="rcA" title="中山">
<div class="unit"><div class="time">9月25日（金曜）10時30分</div><div class="cushion">9.5</div></div>
<div class="unit"><div class="time">9月22日（火曜）7時00分</div><div class="cushion">7.4</div></div>
</div>
<div id="rcB" title="阪神">
<div class="unit"><div class="time">9月25日（金曜）10時00分</div><div class="cushion">8.3</div></div>
<div class="unit"><div class="time">壊れた行</div><div class="cushion">--</div></div>
</div></div>'''

MOIST = '''<div id="moist_data_list">
<div id="rcA" title="中山">
<div class="unit">
<div class="time">9月25日（金曜）10時30分</div>
<div class="turf"><span class="mg" data-condition="hard">12.7</span><span class="m4c" data-condition="hard">13.3</span></div>
<div class="dirt"><span class="mg" data-condition="hard">6.9</span><span class="m4c" data-condition="hard">6.8</span></div>
<ul class="note_list"><li>注記：特になし</li></ul>
</div></div></div>'''


class TestCushion(unittest.TestCase):
    def test_parses_each_venue_newest_first(self):
        c = parse_cushion(CUSHION)
        self.assertEqual(list(c), ["中山", "阪神"])
        self.assertEqual(c["中山"][0]["クッション値"], 9.5)
        self.assertEqual(c["中山"][0]["時刻"], "9月25日（金曜）10時30分")
        self.assertEqual(c["中山"][1]["クッション値"], 7.4)

    def test_unreadable_value_is_dropped_not_invented(self):
        self.assertEqual(len(parse_cushion(CUSHION)["阪神"]), 1)

    def test_labels_follow_jra_table(self):
        self.assertEqual(cushion_label(12.0), "硬め")
        self.assertEqual(cushion_label(10.0), "やや硬め")
        self.assertEqual(cushion_label(9.5), "標準")
        self.assertEqual(cushion_label(8.0), "標準")
        self.assertEqual(cushion_label(7.4), "やや軟らかめ")
        self.assertEqual(cushion_label(7.0), "軟らかめ")


class TestMoist(unittest.TestCase):
    def test_turf_and_dirt_goal_and_corner(self):
        m = parse_moist(MOIST)["中山"][0]
        self.assertEqual(m["芝"], {"ゴール前": 12.7, "4コーナー": 13.3})
        self.assertEqual(m["ダ"], {"ゴール前": 6.9, "4コーナー": 6.8})
        self.assertEqual(m["注記"], "注記：特になし")

    def test_summary_mentions_value_and_time(self):
        info = {"クッション値": parse_cushion(CUSHION), "含水率": parse_moist(MOIST)}
        lines = summary_lines(info, ["中山"])
        self.assertEqual(len(lines), 1)
        self.assertIn("9.5（標準", lines[0])
        self.assertIn("芝 12.7/13.3%", lines[0])


if __name__ == "__main__":
    unittest.main()
