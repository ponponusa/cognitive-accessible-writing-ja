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


if __name__ == "__main__":
    unittest.main()
