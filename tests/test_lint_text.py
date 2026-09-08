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

ISSUE_5_PROSE = (
    "設定ファイルの必須項目を確認したうえで、出力先のディスク残量を見てください。\n"
    "残量が不足している場合は、古い出力を退避してから再実行してください。\n"
    "退避先のパスは運用手順書に記載しています。\n"
)
ISSUE_5_TABLE = (
    "## 判定\n\n"
    "| 観点 | 判定 | 根拠 |\n|---|---|---|\n"
    "| 設計 | 🟢 | 指摘なし |\n"
    "| 実装 | 🟡 | 二つのモジュールで日付の扱いが揃っていない |\n"
    "| テスト | 🟢 | 3 パターンを網羅している |\n"
    "| 性能 | 🟢 | 追加コストなし |\n\n"
)


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
                    metrics = report["metrics"]["by_kind"]["list_item"]
                    self.assertEqual(metrics["sentences"], 4)
                    self.assertEqual(metrics["max_sentence_chars"], 8 + len(ending))
                    self.assertEqual(metrics["paragraphs"], 4)
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
        self.assertEqual(report["metrics"]["by_kind"]["list_item"]["sentences"], 5)
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
                metrics = report["metrics"]["all_units"]
                self.assertEqual(metrics["sentences"], 10)
                self.assertEqual(metrics["median_sentence_chars"], 2)
                self.assertEqual(metrics["max_sentence_chars"], 74 + len(ending))
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
                self.assertEqual(report["metrics"]["all_units"], expected["metrics"]["all_units"])
                self.assertEqual(
                    report["metrics"]["by_kind"]["table_cell"],
                    expected["metrics"]["by_kind"]["prose"],
                )
                self.assertEqual(report["findings"], expected["findings"])

    def test_escaped_pipes_and_inline_code_stay_within_cells(self) -> None:
        report = lint_text.analyze_text(
            "| 項目 | 内容 |\n|---|---|\n"
            "| A\\|B | `left|right` を確認します |"
        )
        expected = lint_text.analyze_text("項目\n\n内容\n\nA|B\n\nを確認します")
        self.assertEqual(report["metrics"]["all_units"], expected["metrics"]["all_units"])

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
        self.assertEqual(report["metrics"]["all_units"]["sentences"], 6)
        for kind in ("prose", "table_cell", "list_item"):
            self.assertEqual(report["metrics"]["by_kind"][kind]["sentences"], 2)
        self.assertNotIn("dense-paragraph", {f["rule"] for f in report["findings"]})

    def test_prose_statistics_are_unaffected_by_tables_and_lists(self) -> None:
        for profile in lint_text.PROFILES:
            baseline = lint_text.analyze_text(ISSUE_5_PROSE, profile)["metrics"]
            self.assertEqual(baseline["sentences"], 3)
            self.assertEqual(baseline["median_sentence_chars"], 34)
            self.assertEqual(baseline["max_sentence_chars"], 38)
            for extra in (ISSUE_5_TABLE, ISSUE_5_TABLE * 3, "- 確認\n- 🟢\n\n"):
                with self.subTest(profile=profile, extra=extra):
                    metrics = lint_text.analyze_text(extra + ISSUE_5_PROSE, profile)["metrics"]
                    for key, value in baseline["by_kind"]["prose"].items():
                        self.assertEqual(metrics[key], value)
                    self.assertEqual(metrics["by_kind"]["prose"], baseline["by_kind"]["prose"])

    def test_population_counts_and_combined_median_are_preserved(self) -> None:
        metrics = lint_text.analyze_text(ISSUE_5_TABLE + ISSUE_5_PROSE)["metrics"]
        self.assertEqual(metrics["by_kind"]["table_cell"]["sentences"], 15)
        self.assertEqual(metrics["by_kind"]["table_cell"]["paragraphs"], 15)
        self.assertEqual(metrics["by_kind"]["list_item"]["sentences"], 0)
        self.assertEqual(metrics["all_units"]["sentences"], 18)
        self.assertEqual(metrics["all_units"]["paragraphs"], 18)
        self.assertEqual(metrics["all_units"]["median_sentence_chars"], 2)
        for field in ("sentences", "paragraphs"):
            self.assertEqual(
                metrics["all_units"][field],
                sum(values[field] for values in metrics["by_kind"].values()),
            )

    def test_short_and_unpunctuated_prose_is_not_filtered(self) -> None:
        metrics = lint_text.analyze_text("はい。\n\n確認")["metrics"]
        self.assertEqual(metrics["sentences"], 2)
        self.assertEqual(metrics["median_sentence_chars"], 2.5)

    def test_empty_prose_population_is_not_reported_as_zero_length(self) -> None:
        for text in ("", "# 見出し\n```text\n本文\n```", ISSUE_5_TABLE, "- 確認"):
            with self.subTest(text=text):
                report = lint_text.analyze_text(text)
                metrics = report["metrics"]
                self.assertEqual(metrics["sentences"], 0)
                self.assertIsNone(metrics["median_sentence_chars"])
                self.assertIsNone(metrics["max_sentence_chars"])
                for values in metrics["by_kind"].values():
                    if values["sentences"] == 0:
                        self.assertIsNone(values["median_sentence_chars"])
                        self.assertIsNone(values["max_sentence_chars"])
                self.assertIn("median n/a", lint_text.render_text_report(report))

    def test_long_nonprose_units_remain_in_findings(self) -> None:
        body = "条件と例外の確認が必要です" * 8
        for text, kind in ((f"| 確認 |\n|---|\n| {body} |", "table_cell"), (f"- {body}", "list_item")):
            with self.subTest(kind=kind):
                report = lint_text.analyze_text(text)
                self.assertEqual(report["metrics"]["sentences"], 0)
                self.assertEqual(report["metrics"]["by_kind"][kind]["max_sentence_chars"], len(body))
                self.assertEqual(report["metrics"]["all_units"]["max_sentence_chars"], len(body))
                self.assertIn("very-long-sentence", {f["rule"] for f in report["findings"]})

    def test_text_report_labels_each_population(self) -> None:
        output = lint_text.render_text_report(lint_text.analyze_text(ISSUE_5_TABLE + ISSUE_5_PROSE))
        lines = output.splitlines()
        prose = next(line for line in lines if line.startswith("Metrics (prose):"))
        table = next(line for line in lines if line.startswith("Metrics (table_cell):"))
        combined = next(line for line in lines if line.startswith("Metrics (all_units):"))
        self.assertIn("3 sentences, median 34 chars/sentence", prose)
        self.assertIn("15 sentences", table)
        self.assertIn("18 sentences, median 2.0 chars/sentence", combined)

    def test_frontmatter_is_excluded_from_metrics_and_findings(self) -> None:
        metadata = (
            'type: Survey\n'
            'title: キャッシュ導入の調査\n'
            'description: 検索結果のキャッシュを導入する前に、更新反映までの時間と画面要件を確認した。対象は一覧画面と詳細画面。\n'
            'tags: [cache, survey]\n'
            'generated: {by: tool, at: "2026-09-08T10:00:00+09:00"}\n'
        )
        body = '# キャッシュ導入の調査\n\n検索結果の表示にはキャッシュを使います。\n'
        for closing in ('---', '...'):
            for newline in ('\n', '\r\n'):
                for bom in ('', '\ufeff'):
                    with self.subTest(closing=closing, newline=newline, bom=bom):
                        text = bom + ('---\n' + metadata + closing + '\n\n' + body).replace('\n', newline)
                        report = lint_text.analyze_text(text)
                        self.assertEqual(report, lint_text.analyze_text(body))
                        self.assertEqual(report['metrics']['sentences'], 1)
                        self.assertEqual(report['metrics']['max_sentence_chars'], 20)

    def test_frontmatter_only_document_has_no_analysis_units(self) -> None:
        for text in ('---\ntitle: 調査\n---', '---\ndescription: |\n  長い説明。\n  続き。\n...\n'):
            with self.subTest(text=text):
                self.assertEqual(lint_text.analyze_text(text), lint_text.analyze_text(''))

    def test_horizontal_rules_inside_body_do_not_remove_content(self) -> None:
        for prefix in ('本文です。\n', '\n'):
            with self.subTest(prefix=prefix):
                text = prefix + '---\n調査内容です。\n---\n結論です。'
                expected = prefix + '\n調査内容です。\n\n結論です。'
                self.assertEqual(lint_text.analyze_text(text), lint_text.analyze_text(expected))

    def test_unclosed_frontmatter_retains_content(self) -> None:
        body = 'title: 調査\n\n本文は保持します。'
        self.assertEqual(lint_text.analyze_text('---\n' + body), lint_text.analyze_text(body))

    def test_indented_frontmatter_terminator_does_not_close_block(self) -> None:
        text = '---\ndescription: |\n  ---\n  説明の続き。\n---\n本文です。'
        self.assertEqual(lint_text.analyze_text(text), lint_text.analyze_text('本文です。'))

    def test_quote_markers_do_not_change_list_metrics_or_findings(self) -> None:
        content = (
            '**確認事項**（反映には数分かかる）\n\n'
            '- 設定ファイルの必須項目\n'
            '- 出力先のディスク残量\n'
            '- 直近のバックアップの日時\n'
            '- 再起動の実施者\n\n'
            '確認が終わったら再起動してください。'
        )
        intro = '導入手順は次のとおりです。\n\n'
        for prefix in ('> ', '>', '>> ', '> > ', '  > '):
            with self.subTest(prefix=prefix):
                quoted = '\n'.join(prefix + line for line in content.splitlines())
                report = lint_text.analyze_text(intro + quoted)
                self.assertEqual(report, lint_text.analyze_text(intro + content))
                self.assertEqual(report['metrics']['by_kind']['list_item']['sentences'], 4)
                self.assertEqual(report['metrics']['sentences'], 3)
                self.assertEqual(report['metrics']['max_sentence_chars'], 19)

    def test_quote_blank_lines_and_depth_changes_separate_units(self) -> None:
        quoted = '引用前\n> 外側\n>> 内側\n> 外側に戻る\n>\n> 別の段落\n引用後'
        plain = '引用前\n\n外側\n\n内側\n\n外側に戻る\n\n別の段落\n\n引用後'
        self.assertEqual(lint_text.analyze_text(quoted), lint_text.analyze_text(plain))

    def test_quoted_headings_tables_and_code_use_existing_rules(self) -> None:
        content = (
            '# 見出し\n\n'
            '| 項目 | 内容 |\n|---|---|\n| 設定 | 確認します。 |\n\n'
            '別の表\n\n項目 | 内容\n--- | ---\n設定 | 保存します。\n\n'
            '```python\nprint("(" * 200)\n```\n\n'
            '- 確認します。\n  記録します。\n  - 完了します。'
        )
        quoted = '\n'.join('> ' + line for line in content.splitlines())
        self.assertEqual(lint_text.analyze_text(quoted), lint_text.analyze_text(content))

    def test_quote_depth_changes_reset_table_detection(self) -> None:
        for text, expected in (
            ('| 項目 |\n|---|\n| 内容 |\n> A | B', '| 項目 |\n|---|\n| 内容 |\n\nA | B'),
            ('A | B\n> --- | ---', 'A | B\n\n--- | ---'),
        ):
            with self.subTest(text=text):
                self.assertEqual(lint_text.analyze_text(text), lint_text.analyze_text(expected))

    def test_literal_greater_than_is_preserved(self) -> None:
        for text in ('値が 5 > 3 であることを確認します。', r'\> は記号です。'):
            with self.subTest(text=text):
                self.assertEqual(lint_text.extract_units(text)[0].text, text)

    def test_long_quoted_content_is_still_checked(self) -> None:
        text = '条件と例外の確認が必要です' * 8
        for prefix, kind in (('> ', 'prose'), ('> - ', 'list_item')):
            with self.subTest(kind=kind):
                report = lint_text.analyze_text(prefix + text)
                self.assertEqual(report['metrics']['by_kind'][kind]['max_sentence_chars'], len(text))
                self.assertIn('very-long-sentence', {f['rule'] for f in report['findings']})

    def test_frontmatter_is_not_removed_inside_a_quote(self) -> None:
        quoted = '> ---\n> title: 引用内容\n> ---\n> 本文です。'
        self.assertEqual(
            lint_text.analyze_text(quoted),
            lint_text.analyze_text('title: 引用内容\n\n本文です。'),
        )


if __name__ == "__main__":
    unittest.main()
