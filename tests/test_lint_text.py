import importlib.util
from pathlib import Path
import sys
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "lint_text.py"
SPEC = importlib.util.spec_from_file_location("lint_text", SCRIPT)
assert SPEC and SPEC.loader
lint_text = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lint_text
SPEC.loader.exec_module(lint_text)


class LintTextTests(unittest.TestCase):
    def rules(self, text: str, profile: str = "balanced") -> set[str]:
        report = lint_text.analyze_text(text, profile)
        return {item["rule"] for item in report["findings"]}

    def test_low_interruption_flags_parentheses(self) -> None:
        rules = self.rules(
            "本番反映は金曜日です（承認が遅れた場合は延期します）。",
            "low-interruption",
        )
        self.assertIn("parenthetical-density", rules)

    def test_double_negative_is_flagged(self) -> None:
        rules = self.rules("対応できないわけではないです。")
        self.assertIn("double-negative", rules)

    def test_fenced_code_is_ignored(self) -> None:
        report = lint_text.analyze_text(
            "次を実行します。\n\n```python\nprint('(' * 200)\n```\n",
            "low-interruption",
        )
        self.assertEqual(report["metrics"]["parenthetical_segments"], 0)

    def test_very_long_sentence_is_flagged(self) -> None:
        text = (
            "設定ファイルを開いて接続先を変更した後に保存し、"
            "続いてテストを実行し、失敗した場合にはログを確認して、"
            "認証エラーである場合に限ってトークンを再発行し、"
            "再度テストを実行して結果を記録してください。"
        )
        rules = self.rules(text, "minimal")
        self.assertTrue(
            {"long-sentence", "very-long-sentence"}.intersection(rules)
        )

    def test_unbalanced_parenthesis_is_flagged(self) -> None:
        rules = self.rules("説明（補足です。")
        self.assertIn("unbalanced-parenthesis", rules)

    def test_list_items_are_independent_of_markers_and_punctuation(self) -> None:
        items = ["入力を確認します", "出力を確認します", "設定を確認します", "日時を確認します"]
        for marker in ("-", "*", "+", "1.", "1)", "- [ ]", "- [x]"):
            for ending in ("", "。", "！", "?"):
                with self.subTest(marker=marker, ending=ending):
                    report = lint_text.analyze_text(
                        "\n".join(f"{marker} {item}{ending}" for item in items),
                        "low-interruption",
                    )
                    self.assertEqual(report["metrics"]["sentences"], 4)
                    self.assertEqual(report["metrics"]["max_sentence_chars"], 8 + len(ending))
                    self.assertEqual(report["metrics"]["paragraphs"], 4)
                    self.assertNotIn("dense-paragraph", {f["rule"] for f in report["findings"]})

    def test_one_sentence_per_line_is_not_dense(self) -> None:
        lines = ["本番反映は金曜日です。", "承認が遅れた場合は延期します。", "延期の連絡は前日までに行います。"]
        for line_break in ("\n", "  \n", "\\\n"):
            with self.subTest(line_break=line_break):
                report = lint_text.analyze_text(line_break.join(lines), "low-interruption")
                self.assertEqual(report["metrics"]["sentences"], 3)
                self.assertEqual(report["metrics"]["max_sentence_chars"], 16)
                self.assertNotIn("dense-paragraph", {f["rule"] for f in report["findings"]})

    def test_dense_units_still_report_multiple_sentences(self) -> None:
        body = "入力を確認します。設定を確認します。日時を確認します。"
        for text in (body, f"- {body}", f"| 確認 |\n|---|\n| {body} |"):
            with self.subTest(text=text):
                findings = lint_text.analyze_text(text, "low-interruption")["findings"]
                dense = [f for f in findings if f["rule"] == "dense-paragraph"]
                self.assertEqual(len(dense), 1)
                self.assertEqual(dense[0]["excerpt"], body)

    def test_list_continuations_and_nested_items(self) -> None:
        report = lint_text.analyze_text(
            "- 入力を確認します。\n"
            "  設定を確認します。\n"
            "  日時を確認します。\n"
            "  - 保存します。\n"
            "- 終了します。",
            "low-interruption",
        )
        self.assertEqual(report["metrics"]["sentences"], 5)
        dense = [f for f in report["findings"] if f["rule"] == "dense-paragraph"]
        self.assertEqual(len(dense), 1)
        self.assertNotIn("保存", dense[0]["excerpt"])
        self.assertNotIn("終了", dense[0]["excerpt"])

    def test_table_cells_are_checked_without_sentence_ending(self) -> None:
        cell = (
            "前回指摘の矛盾は解消したが二つのモジュールで日付の扱いが揃っておらず、"
            "揃えるにはクエリと変換処理と判定条件とテストの 4 点を連動して変更する必要がある"
        )
        for ending in ("", "。"):
            with self.subTest(ending=ending):
                report = lint_text.analyze_text(
                    "判定結果を表にまとめます。\n\n"
                    "| 観点 | 判定 | 根拠 |\n|---|:---:|---:|\n"
                    f"| 設計 | 🟡 | {cell}{ending} |\n"
                    "| テスト | 🟢 | 追加テストは 3 パターンを網羅している |"
                )
                self.assertEqual(report["metrics"]["sentences"], 10)
                self.assertEqual(report["metrics"]["median_sentence_chars"], 2)
                self.assertEqual(report["metrics"]["max_sentence_chars"], 74 + len(ending))
                long = [f for f in report["findings"] if f["rule"] == "long-sentence"]
                self.assertEqual(len(long), 1)
                self.assertEqual(long[0]["excerpt"], cell + ending)

    def test_table_syntax_does_not_affect_metrics(self) -> None:
        with_pipes = "| 項目 | 内容 |\n|:---|---:|\n| 設定 | 保存します。確認します。 |"
        without_pipes = "項目 | 内容\n:--- | ---:\n設定 | 保存します。確認します。"
        expected = lint_text.analyze_text("項目\n\n内容\n\n設定\n\n保存します。確認します。")
        for table in (with_pipes, without_pipes):
            with self.subTest(table=table):
                report = lint_text.analyze_text(table)
                self.assertEqual(report["metrics"], expected["metrics"])
                self.assertEqual(report["findings"], expected["findings"])

    def test_escaped_pipes_and_inline_code_stay_within_cells(self) -> None:
        report = lint_text.analyze_text(
            "| 項目 | 内容 |\n|---|---|\n"
            "| A\\|B | `left|right` を確認します |"
        )
        expected = lint_text.analyze_text("項目\n\n内容\n\nA|B\n\nを確認します")
        self.assertEqual(report["metrics"], expected["metrics"])

    def test_soft_wrapped_sentence_is_checked_as_one_sentence(self) -> None:
        report = lint_text.analyze_text("設定ファイルを開いて\n接続先を確認します。")
        self.assertEqual(report["metrics"]["sentences"], 1)
        self.assertEqual(report["metrics"]["max_sentence_chars"], 20)

    def test_markdown_blocks_separate_adjacent_prose(self) -> None:
        text = (
            "# 確認。\n"
            "開始します。\n"
            "- 入力を確認します。\n"
            "- 設定を確認します。\n"
            "| 項目 |\n|---|\n| 日時 |\n"
            "終了します。\n"
            "---\n"
            "```text\n無視します。無視します。無視します。\n```"
        )
        report = lint_text.analyze_text(text, "low-interruption")
        self.assertEqual(report["metrics"]["sentences"], 6)
        self.assertNotIn("dense-paragraph", {f["rule"] for f in report["findings"]})


if __name__ == "__main__":
    unittest.main()
