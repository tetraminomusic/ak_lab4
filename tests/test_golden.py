# tests/test_golden.py
import logging
import os
import sys

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import translator
from machine import load_sources, run_simulation

JOURNAL_HEAD = 30
JOURNAL_TAIL = 10


def trim_journal(messages: list) -> str:
    lines = []
    for message in messages:
        lines.extend(line for line in str(message).splitlines() if line.strip())

    if len(lines) <= JOURNAL_HEAD + JOURNAL_TAIL:
        return "\n".join(lines)

    keep = set(range(JOURNAL_HEAD))
    keep.update(range(len(lines) - JOURNAL_TAIL, len(lines)))
    keep.update(i for i, line in enumerate(lines) if line.startswith("[ТАКТ"))

    journal = []
    previous = -1

    for i in sorted(keep):
        if i != previous + 1:
            journal.append(f"... пропущено строк: {i - previous - 1} ...")
        journal.append(lines[i])
        previous = i

    return "\n".join(journal)


@pytest.mark.golden_test("golden/*.yml")
def test_golden(golden, tmp_path, caplog):

    # Интеграционный Golden-тест с автообновлением эталонов.
    lisp_code = golden["in_source"]
    schedule = [(int(tick), char) for tick, char in golden.get("in_schedule", [])]
    max_ticks = golden.get("in_ticks", 5000)

    source_file = tmp_path / "program.lisp"
    bin_file = tmp_path / "program.bin"
    listing_file = tmp_path / "listing.txt"
    source_file.write_text(lisp_code, encoding="utf-8")

    # Компиляция
    translator.compile_file(str(source_file), str(bin_file), str(listing_file))
    listing_content = listing_file.read_text(encoding="utf-8").strip()
    sources = load_sources(str(listing_file))

    # Симуляция
    with caplog.at_level(logging.DEBUG):
        output, _ = run_simulation(
            str(bin_file),
            schedule,
            max_ticks=max_ticks,
            sources=sources,
        )

    # Сверка с эталоном
    assert listing_content == golden.out["out_code_hex"]
    assert output == golden.out["out_stdout"]
    assert trim_journal(caplog.messages) == golden.out["out_log"]
