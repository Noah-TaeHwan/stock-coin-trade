"""Number receipts: the model writes placeholders, the server fills in values.

The model's final answer is JSON with a Markdown template and a list of
numbers. Each number names a receipt (a backtest this conversation ran or
looked up) and a path inside it, e.g. `metrics.sharpe`. `render` resolves every
path from the stored tool output and refuses the answer if

- a number points at a receipt the conversation never produced,
- a path does not resolve to a number, or
- the template contains digits outside the placeholders that are not a known
  identifier (dates, symbols, strategy ids, receipt id prefixes).

So a number in a rendered answer can always be traced to a calculation, and a
number the model typed itself cannot reach the user.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

PLACEHOLDER = re.compile(r"\{\{\s*(n\d{1,3})\s*\}\}")
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
DIGIT = re.compile(r"\d")
# "1. " / "2) " at the start of a line is a Markdown list marker, not a claim.
LIST_MARKER = re.compile(r"^(\s*)\d{1,2}[.)]\s", re.MULTILINE)
FORMATS = ("percent", "ratio", "integer", "krw", "number")

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "numbers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "receipt_id": {"type": "string"},
                    "path": {"type": "string"},
                    "format": {"type": "string", "enum": list(FORMATS)},
                },
                "required": ["id", "receipt_id", "path", "format"],
                "additionalProperties": False,
            },
        },
        "out_of_scope": {"type": "boolean"},
    },
    "required": ["answer", "numbers", "out_of_scope"],
    "additionalProperties": False,
}


class UnreceiptedAnswer(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass
class Ledger:
    """Tool outputs this conversation produced, by receipt id."""

    runs: dict[str, dict] = field(default_factory=dict)
    identifiers: set[str] = field(default_factory=set)

    def add_run(self, run: dict) -> None:
        receipt_id = run["receiptId"]
        self.runs[receipt_id] = run
        params = run.get("parameters") or run.get("receipt", {}).get("params", {})
        for key in ("symbol", "strategy"):
            if params.get(key):
                self.identifiers.add(str(params[key]))
        self.identifiers.add(receipt_id[:12])
        self.identifiers.add(receipt_id)


def resolve(run: dict, path: str) -> float:
    value: object = run
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(path)
        value = value[part]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise TypeError(path)
    return float(value)


def display(value: float, fmt: str) -> str:
    if fmt == "percent":
        return f"{value * 100:+.2f}%"
    if fmt == "ratio":
        return f"{value:.2f}"
    if fmt == "integer":
        return f"{round(value):,}"
    if fmt == "krw":
        return f"{round(value):,}원"
    return f"{value:,.4g}"


def stray_numbers(template: str, identifiers: set[str]) -> list[str]:
    """Digit-bearing tokens in the template that are neither placeholders nor known identifiers."""
    text = PLACEHOLDER.sub(" ", template)
    text = DATE.sub(" ", text)
    text = LIST_MARKER.sub(r"\1- ", text)
    for identifier in sorted(identifiers, key=len, reverse=True):
        text = text.replace(identifier, " ")
    return [token for token in re.findall(r"[^\s]*\d[^\s]*", text) if DIGIT.search(token)]


def render(answer: dict, ledger: Ledger) -> dict:
    """Fill placeholders from the ledger; raise UnreceiptedAnswer if any number is not backed by a receipt."""
    problems: list[str] = []
    values: dict[str, dict] = {}
    for number in answer["numbers"]:
        run = ledger.runs.get(number["receipt_id"])
        if run is None:
            problems.append(
                f"{number['id']}: receipt {number['receipt_id'][:12]} was not produced in this conversation"
            )
            continue
        if number["format"] not in FORMATS:
            problems.append(f"{number['id']}: unknown format {number['format']!r}")
            continue
        try:
            value = resolve(run, number["path"])
        except (KeyError, TypeError):
            problems.append(f"{number['id']}: {number['path']} is not a number in receipt {number['receipt_id'][:12]}")
            continue
        values[number["id"]] = {
            "id": number["id"],
            "value": value,
            "display": display(value, number["format"]),
            "receiptId": number["receipt_id"],
            "path": number["path"],
            "format": number["format"],
        }
    used = set(PLACEHOLDER.findall(answer["answer"]))
    for missing in sorted(used - set(values) - {n["id"] for n in answer["numbers"]}):
        problems.append(f"{missing}: placeholder has no entry in numbers")
    strays = stray_numbers(answer["answer"], ledger.identifiers)
    if strays:
        problems.append("numbers written without a receipt: " + ", ".join(strays[:10]))
    if problems:
        raise UnreceiptedAnswer(problems)
    text = PLACEHOLDER.sub(lambda match: values[match.group(1)]["display"], answer["answer"])
    return {
        "template": answer["answer"],
        "text": text,
        "numbers": [values[key] for key in sorted(used, key=lambda k: int(k[1:]))],
        "receipts": sorted({values[key]["receiptId"] for key in used}),
    }
