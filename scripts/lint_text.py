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
from typing import Iterable


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
ROUND_OPEN = {"(": ")", "（": "）"}
ROUND_CLOSE = {")": "(", "）": "（"}


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    message: str
    excerpt: str = ""
    position: int | None = None


def strip_nonprose(text: str) -> str:
    """Remove fenced/inline code and retain link labels."""
    text = CODE_FENCE_RE.sub("", text)
    text = INLINE_CODE_RE.sub("", text)
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    return text


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
        if sentence.startswith(("#", "-", "*", "|")) and "。" not in sentence:
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
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if paragraph.startswith(("```", "#", "|")):
            continue
        count = len(split_sentences(paragraph))
        if count:
            yield paragraph, count


def analyze_text(text: str, profile_name: str = "balanced") -> dict:
    if profile_name not in PROFILES:
        raise ValueError(f"Unknown profile: {profile_name}")

    cfg = PROFILES[profile_name]
    prose = strip_nonprose(text)
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
                    f"一段落に {count} 文あります。"
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

    return {
        "profile": profile_name,
        "metrics": {
            "characters": len(prose),
            "sentences": len(sentences),
            "median_sentence_chars": statistics.median(lengths) if lengths else 0,
            "max_sentence_chars": max(lengths) if lengths else 0,
            "parenthetical_segments": parenthetical_count,
            "parenthetical_max_depth": max_depth,
            "paragraphs": sum(1 for _ in re.split(r"\n\s*\n", prose) if _.strip()),
        },
        "findings": [asdict(finding) for finding in findings],
        "notice": (
            "This is a heuristic review aid. A clean result does not prove "
            "cognitive accessibility or comprehension."
        ),
    }


def render_text_report(report: dict) -> str:
    metrics = report["metrics"]
    lines = [
        f"Profile: {report['profile']}",
        (
            "Metrics: "
            f"{metrics['characters']} chars, "
            f"{metrics['sentences']} sentences, "
            f"median {metrics['median_sentence_chars']} chars/sentence, "
            f"max {metrics['max_sentence_chars']}, "
            f"{metrics['parenthetical_segments']} parenthetical segments"
        ),
        "",
    ]

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
