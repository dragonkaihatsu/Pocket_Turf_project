"""同じ設定から出る出力は、同じスコアで並んでいなければならない。

## 新聞・一覧・カードが旧尺度で出ていた（2026-09-19・本人が画像で気づいた）

`keiba/shinbun.py` `keiba/kompi.py` `keiba/daily.py` が `score_race` に
`records` を渡していなかったため、持ち時計指数が作れず**全馬が上がり3Fの
代替に落ちていた**。コース適性・距離適性も中立で、乗り替わり補正も発火
しない。結果、同じ日の同じ設定から

    予想テキスト  中山9R  ◎6 ○3 ▲2 △9 …   （持ち時計あり）
    新聞・一覧    中山9R  ◎6 ○2 ▲9 △3 …   （上がり3Fだけ）

と**2〜4位の並びが違うものが2つ出ていた**。配信の既定は新聞なので、
公表していたのは旧尺度のほうだった。エラーは出ず、もっともらしい別の
並びが静かに出る——戦績の既定が薄いファイルを指していた件と同じ形。

`daily.py` はさらに `venue` も落としていた（`RaceEntry.from_dict` が
宣言済みフィールドしか拾わないため）。`score_horse` は「渡さないと
コース適性は中立になる」と明記してあった。
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# score_race を呼ぶすべての出力経路。増えたらここに足す
BUILDERS = ("keiba/cli.py", "keiba/shinbun.py", "keiba/kompi.py",
            "keiba/daily.py", "keiba/stats.py")


def score_race_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "score_race"):
            yield node


class TestEveryBuilderPassesRecords(unittest.TestCase):
    def test_records_and_as_of_and_venue(self):
        """**キーワードで渡していること**をソースで固定する。

        振る舞いのテストでも捕まえられるが、経路が増えたときに
        「新しい出力だけ旧尺度」という状態を防げない。`profile` の
        `assert_same_profile` を7本すべてに入れたのと同じ番犬。
        """
        seen = 0
        for rel in BUILDERS:
            p = ROOT / rel
            for call in score_race_calls(p):
                seen += 1
                kw = {k.arg for k in call.keywords}
                for need in ("records", "as_of", "venue"):
                    self.assertIn(
                        need, kw,
                        f"{rel}: score_race に {need}= を渡していない。"
                        f"渡さないと持ち時計・コース適性が静かに死ぬ")
        self.assertGreaterEqual(seen, 5, "score_race の呼び出しが見つからない")

    def test_no_other_module_calls_score_race(self):
        """出力経路を BUILDERS に列挙しきれているか。"""
        others = [p.relative_to(ROOT).as_posix()
                  for p in (ROOT / "keiba").glob("*.py")
                  if p.relative_to(ROOT).as_posix() not in BUILDERS
                  and any(score_race_calls(p))]
        self.assertEqual(others, [],
                         f"BUILDERS に入っていない呼び出し: {others}")


class TestOrderAgrees(unittest.TestCase):
    """新聞の並びが `assign_marks` と一致する（軸も同じ）。"""

    def test_shinbun_row_matches_assign_marks(self):
        import json
        import tempfile

        from keiba.marks import assign_marks
        from keiba.models import load_horses
        from keiba.scoring import score_race
        from keiba.shinbun import race_row

        rows = [
            "馬番,枠番,馬名,性齢,騎手,脚質,単勝オッズ,人気,前走着順,"
            "前走レース名,上がり3F,調教評価",
            "1,1,アルファ,牡4,テスト,先行,2.0,1,1,A,34.0,",
            "2,2,ブラボー,牡4,テスト,差し,3.0,2,2,A,35.0,",
            "3,3,チャーリー,牡4,テスト,逃げ,5.0,3,3,A,36.0,",
            "4,4,デルタ,牡4,テスト,追込,9.0,4,4,A,37.0,",
            "5,5,エコー,牡4,テスト,先行,15.0,5,5,A,38.0,",
        ]
        with tempfile.TemporaryDirectory() as td:
            ent = Path(td) / "2026-09-19_中山09R_テスト_出走馬.csv"
            ent.write_text("\n".join(rows) + "\n", encoding="utf-8-sig")
            cfg = {"heading": "2026-09-19 テスト",
                   "races": [{"venue": "中山", "race_no": "9R",
                              "name": "テスト", "entries": str(ent),
                              "kyori": 1200, "surface": "芝1200m",
                              "baba": "良"}]}
            row = race_row(cfg["races"][0], None, "2026-09-19")
            horses = load_horses(ent)
            scores = score_race(horses, None, kyori=1200, records=None,
                                as_of="2026-09-19", venue="中山")
            want = [m.score.horse.umaban
                    for m in assign_marks(scores, baba="良")]
            got = [c.umaban for c in row.cells]
            self.assertEqual(got, want[:len(got)])
            json.dumps(cfg)          # 設定がJSONにできる形であること


if __name__ == "__main__":
    unittest.main()
