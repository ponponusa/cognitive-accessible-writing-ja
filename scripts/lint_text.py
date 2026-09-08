#!/usr/bin/env python3
"""Heuristic linter for Cognitive Accessible Writing JA.

This tool finds review candidates. It does not certify cognitive accessibility.
It uses only Python's standard library.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Literal


PROFILES = {
    "balanced": {
        "sentence_soft_max_chars": 60,
        "sentence_hard_review_chars": 90,
        "paragraph_max_sentences": 3,
        "parenthetical_soft_max_per_1000": 4,
        "comma_soft_max_per_sentence": 3,
    },
    "low-interruption": {
        "sentence_soft_max_chars": 50,
        "sentence_hard_review_chars": 75,
        "paragraph_max_sentences": 2,
        "parenthetical_soft_max_per_1000": 0,
        "comma_soft_max_per_sentence": 2,
    },
    "action-first": {
        "sentence_soft_max_chars": 55,
        "sentence_hard_review_chars": 85,
        "paragraph_max_sentences": 3,
        "parenthetical_soft_max_per_1000": 3,
        "comma_soft_max_per_sentence": 3,
    },
    "literal-explicit": {
        "sentence_soft_max_chars": 60,
        "sentence_hard_review_chars": 90,
        "paragraph_max_sentences": 3,
        "parenthetical_soft_max_per_1000": 3,
        "comma_soft_max_per_sentence": 3,
    },
    "deep-navigable": {
        "sentence_soft_max_chars": 65,
        "sentence_hard_review_chars": 100,
        "paragraph_max_sentences": 4,
        "parenthetical_soft_max_per_1000": 5,
        "comma_soft_max_per_sentence": 4,
    },
    "minimal": {
        "sentence_soft_max_chars": 45,
        "sentence_hard_review_chars": 70,
        "paragraph_max_sentences": 2,
        "parenthetical_soft_max_per_1000": 0,
        "comma_soft_max_per_sentence": 2,
    },
}

DOUBLE_NEGATIVE_PATTERNS = [
    r"ないわけではない",
    r"なくはない",
    r"ないこともない",
    r"できないとは限らない",
    r"不可能ではない",
]

AMBIGUOUS_REFERENT_PATTERNS = [
    r"これ",
    r"それ",
    r"この点",
    r"その点",
    r"前述",
    r"上述",
    r"同様",
    r"当該",
]

FILLER_OPENERS = [
    r"^\s*ご質問ありがとうございます[。！!]*",
    r"^\s*もちろんです[。！!]*",
    r"^\s*承知しました[。！!]*",
    r"^\s*以下に(?:説明|整理|紹介|記載)します[。]*",
    r"^\s*まず(?:は)?、",
    r"^\s*結論から(?:言う|申し上げる)と、",
]

HEDGE_PATTERNS = [
    r"可能性があります",
    r"と考えられます",
    r"と思われます",
    r"かもしれません",
]

CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
SENTENCE_RE = re.compile(r"[^。！？!?\n]+[。！？!?]?")
LIST_ITEM_RE = re.compile(r"^(\s*)(?:[-+*]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*)$")
HEADING_RE = re.compile(r"^#{1,6}(?:\s|$)")
THEMATIC_BREAK_RE = re.compile(r"^(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$")
SENTENCE_END_RE = re.compile(r"[。！？!?][\"'」』）)\]]*$")
ROUND_OPEN = {"(": ")", "（": "）"}
ROUND_CLOSE = {")": "(", "）": "（"}


@dataclass(frozen=True)
class TextUnit:
    kind: Literal["prose", "table_cell", "list_item"]
    text: str


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    message: str
    excerpt: str = ""
    position: int | None = None


def split_table_cells(line: str) -> list[str]:
    """Split structural pipes, keeping escaped pipes in their cell."""
    cells: list[str] = []
    start = 0
    backslashes = 0
    for index, char in enumerate(line):
        if char == "|" and backslashes % 2 == 0:
            cells.append(line[start:index].strip())
            start = index + 1
        backslashes = backslashes + 1 if char == "\\" else 0
    cells.append(line[start:].strip())
    if line.startswith("|"):
        cells.pop(0)
    if start == len(line) and line.endswith("|"):
        cells.pop()
    return [cell.replace(r"\|", "|") for cell in cells]


def is_table_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def markdown_units(text: str) -> list[TextUnit]:
    """Extract prose units for a lightweight, line-oriented Markdown lint.

    Table cells and list items are independent units. In ordinary prose,
    a newline after a complete sentence or a Markdown hard break ends a unit;
    soft-wrapped, unfinished sentences remain together. Indented continuation
    lines belong to their list item, including when they contain full sentences.
    """
    units: list[TextUnit] = []
    pending: list[str] = []
    list_indent: int | None = None
    in_table = False

    def flush() -> None:
        nonlocal list_indent
        if pending:
            kind = "list_item" if list_indent is not None else "prose"
            units.append(TextUnit(kind, " ".join(pending)))
            pending.clear()
        list_indent = None

    lines = text.expandtabs(4).splitlines()
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            flush()
            in_table = False
            continue

        cells = split_table_cells(line)
        next_cells = split_table_cells(lines[index + 1].strip()) if index + 1 < len(lines) else []
        table_row = line.startswith("|") or (
            len(cells) > 1 and (in_table or is_table_separator(next_cells))
        )
        if table_row:
            flush()
            in_table = True
            if not is_table_separator(cells):
                units.extend(TextUnit("table_cell", cell) for cell in cells if cell)
            continue
        in_table = False

        if HEADING_RE.match(line) or THEMATIC_BREAK_RE.fullmatch(line):
            flush()
            continue

        hard_break = raw_line.endswith("  ") or line.endswith("\\")
        if line.endswith("\\"):
            line = line[:-1].rstrip()
        item = LIST_ITEM_RE.match(raw_line)
        if item:
            flush()
            list_indent = len(item.group(1))
            body = item.group(2).strip()
            if body.endswith("\\"):
                body = body[:-1].rstrip()
            if body:
                pending.append(body)
            continue

        indent = len(raw_line) - len(raw_line.lstrip())
        if list_indent is not None and indent <= list_indent:
            flush()
        if line:
            pending.append(line)
        if list_indent is None and (hard_break or SENTENCE_END_RE.search(line)):
            flush()

    flush()
    return units


def extract_units(text: str) -> list[TextUnit]:
    """Remove code/markup while retaining each unit's structural kind."""
    text = CODE_FENCE_RE.sub("\n\n", text)
    text = INLINE_CODE_RE.sub("", text)
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    return markdown_units(text)


def strip_nonprose(text: str) -> str:
    """Remove code/markup and separate all analysis units with blank lines."""
    return "\n\n".join(unit.text for unit in extract_units(text))


def normalize_excerpt(text: str, limit: int = 100) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for match in SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        if not sentence:
            continue
        sentences.append(sentence)
    return sentences


def count_parentheticals(text: str) -> tuple[int, int, list[Finding]]:
    stack: list[tuple[str, int]] = []
    segments = 0
    max_depth = 0
    findings: list[Finding] = []

    for index, char in enumerate(text):
        if char in ROUND_OPEN:
            stack.append((char, index))
            segments += 1
            max_depth = max(max_depth, len(stack))
        elif char in ROUND_CLOSE:
            if not stack:
                findings.append(Finding(
                    rule="unbalanced-parenthesis",
                    severity="error",
                    message="対応する開き括弧がありません。",
                    excerpt=char,
                    position=index,
                ))
                continue
            opener, opener_index = stack.pop()
            if ROUND_OPEN[opener] != char:
                findings.append(Finding(
                    rule="mixed-parenthesis",
                    severity="error",
                    message="丸括弧の種類が対応していません。",
                    excerpt=text[max(0, opener_index - 15): index + 16],
                    position=opener_index,
                ))

    for opener, index in stack:
        findings.append(Finding(
            rule="unbalanced-parenthesis",
            severity="error",
            message="対応する閉じ括弧がありません。",
            excerpt=text[index:index + 60],
            position=index,
        ))

    if max_depth > 1:
        findings.append(Finding(
            rule="nested-parenthesis",
            severity="warning",
            message=f"括弧が {max_depth} 段に入れ子です。独立した文への分離を検討してください。",
        ))

    return segments, max_depth, findings


def count_paragraph_sentences(text: str) -> Iterable[tuple[str, int]]:
    """Count sentences in the normalized units returned by strip_nonprose."""
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        count = len(split_sentences(paragraph))
        if count:
            yield paragraph, count


def summarize_units(units: list[TextUnit]) -> dict:
    """Measure a specific population; empty length distributions are unknown."""
    text = "\n\n".join(unit.text for unit in units)
    lengths = [len(re.sub(r"\s+", "", sentence)) for sentence in split_sentences(text)]
    return {
        "characters": len(text),
        "sentences": len(lengths),
        "median_sentence_chars": statistics.median(lengths) if lengths else None,
        "max_sentence_chars": max(lengths) if lengths else None,
        "paragraphs": len(units),
    }


def analyze_text(text: str, profile_name: str = "balanced") -> dict:
    if profile_name not in PROFILES:
        raise ValueError(f"Unknown profile: {profile_name}")

    cfg = PROFILES[profile_name]
    units = extract_units(text)
    prose = "\n\n".join(unit.text for unit in units)
    sentences = split_sentences(prose)
    findings: list[Finding] = []

    lengths = [len(re.sub(r"\s+", "", sentence)) for sentence in sentences]
    for sentence, length in zip(sentences, lengths):
        if length > cfg["sentence_hard_review_chars"]:
            findings.append(Finding(
                rule="very-long-sentence",
                severity="warning",
                message=(
                    f"一文が {length} 文字です。"
                    f" {cfg['sentence_hard_review_chars']} 文字を超えています。"
                    " 条件、理由、例外を分けられるか確認してください。"
                ),
                excerpt=normalize_excerpt(sentence),
            ))
        elif length > cfg["sentence_soft_max_chars"]:
            findings.append(Finding(
                rule="long-sentence",
                severity="info",
                message=(
                    f"一文が {length} 文字です。"
                    f" ソフト基準 {cfg['sentence_soft_max_chars']} 文字を超えています。"
                ),
                excerpt=normalize_excerpt(sentence),
            ))

        comma_count = sentence.count("、") + sentence.count(",")
        if comma_count > cfg["comma_soft_max_per_sentence"]:
            findings.append(Finding(
                rule="many-commas",
                severity="info",
                message=(
                    f"一文に読点・カンマが {comma_count} 個あります。"
                    " 複数論点や挿入句がないか確認してください。"
                ),
                excerpt=normalize_excerpt(sentence),
            ))

    parenthetical_count, max_depth, parenthetical_findings = count_parentheticals(prose)
    findings.extend(parenthetical_findings)
    allowed_parentheticals = (
        cfg["parenthetical_soft_max_per_1000"] * max(len(prose), 1) / 1000
    )
    if parenthetical_count > allowed_parentheticals:
        severity = "warning" if cfg["parenthetical_soft_max_per_1000"] == 0 else "info"
        findings.append(Finding(
            rule="parenthetical-density",
            severity=severity,
            message=(
                f"丸括弧が {parenthetical_count} 組あります。"
                f" プロファイル {profile_name} の目安を超えています。"
                " 条件、例外、理由、例を本文へ分離できるか確認してください。"
            ),
        ))

    for paragraph, count in count_paragraph_sentences(prose):
        if count > cfg["paragraph_max_sentences"]:
            findings.append(Finding(
                rule="dense-paragraph",
                severity="info",
                message=(
                    f"一つの解析単位に {count} 文あります。"
                    f" 目安は {cfg['paragraph_max_sentences']} 文以下です。"
                ),
                excerpt=normalize_excerpt(paragraph),
            ))

    for pattern in DOUBLE_NEGATIVE_PATTERNS:
        for match in re.finditer(pattern, prose):
            findings.append(Finding(
                rule="double-negative",
                severity="warning",
                message="二重否定または否定の重なりです。肯定形へ直して意味が保てるか確認してください。",
                excerpt=normalize_excerpt(
                    prose[max(0, match.start() - 30): match.end() + 30]
                ),
                position=match.start(),
            ))

    referent_hits = []
    for pattern in AMBIGUOUS_REFERENT_PATTERNS:
        referent_hits.extend(re.finditer(pattern, prose))
    if referent_hits:
        examples = [hit.group(0) for hit in referent_hits[:5]]
        findings.append(Finding(
            rule="referent-review",
            severity="info",
            message=(
                f"指示語候補が {len(referent_hits)} 件あります。"
                f" 例: {', '.join(examples)}。参照先が一意か確認してください。"
            ),
        ))

    for pattern in FILLER_OPENERS:
        match = re.search(pattern, prose)
        if match:
            findings.append(Finding(
                rule="filler-opener",
                severity="info",
                message="内容を進めない前置きの可能性があります。答えを直接始められるか確認してください。",
                excerpt=normalize_excerpt(match.group(0)),
                position=match.start(),
            ))

    hedge_count = sum(len(re.findall(pattern, prose)) for pattern in HEDGE_PATTERNS)
    if hedge_count >= 3:
        findings.append(Finding(
            rule="hedge-density",
            severity="info",
            message=(
                f"不確実性表現が {hedge_count} 件あります。"
                " 真の不確実性は保持し、重複する慎重表現だけを整理してください。"
            ),
        ))

    severity_order = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda item: (severity_order[item.severity], item.rule))

    by_kind = {
        kind: summarize_units([unit for unit in units if unit.kind == kind])
        for kind in ("prose", "table_cell", "list_item")
    }
    return {
        "profile": profile_name,
        "metrics": {
            **by_kind["prose"],
            "parenthetical_segments": parenthetical_count,
            "parenthetical_max_depth": max_depth,
            "by_kind": by_kind,
            "all_units": summarize_units(units),
        },
        "findings": [asdict(finding) for finding in findings],
        "notice": (
            "This is a heuristic review aid. A clean result does not prove "
            "cognitive accessibility or comprehension."
        ),
    }


def render_text_report(report: dict) -> str:
    metrics = report["metrics"]
    lines = [f"Profile: {report['profile']}"]
    populations = [
        ("prose", metrics["by_kind"]["prose"]),
        ("table_cell", metrics["by_kind"]["table_cell"]),
        ("list_item", metrics["by_kind"]["list_item"]),
        ("all_units", metrics["all_units"]),
    ]
    for label, values in populations:
        median = values["median_sentence_chars"]
        maximum = values["max_sentence_chars"]
        lines.append(
            f"Metrics ({label}): {values['characters']} chars, "
            f"{values['sentences']} sentences, "
            f"median {median if median is not None else 'n/a'} chars/sentence, "
            f"max {maximum if maximum is not None else 'n/a'}, "
            f"{values['paragraphs']} units"
        )
    lines.extend([
        f"Parentheticals (all_units): {metrics['parenthetical_segments']} segments, "
        f"max depth {metrics['parenthetical_max_depth']}",
        "",
    ])

    findings = report["findings"]
    if not findings:
        lines.append("No heuristic findings.")
    else:
        for index, finding in enumerate(findings, start=1):
            lines.append(
                f"{index}. [{finding['severity'].upper()}] "
                f"{finding['rule']}: {finding['message']}"
            )
            if finding.get("excerpt"):
                lines.append(f"   {finding['excerpt']}")

    lines.extend(["", f"Notice: {report['notice']}"])
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find Japanese writing patterns that may increase cognitive load. "
            "This tool does not certify accessibility."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        help="Input file. Omit or use '-' to read UTF-8 text from stdin.",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="balanced",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of a text report.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 2 when an error or warning is found.",
    )
    return parser.parse_args(argv)


def read_input(path: str | None) -> str:
    if path in (None, "-"):
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        text = read_input(args.input)
        report = analyze_text(text, args.profile)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_text_report(report))

    if args.strict and any(
        finding["severity"] in {"error", "warning"}
        for finding in report["findings"]
    ):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
