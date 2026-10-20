# tests/test_golden.py
import logging
import os
import struct
import sys
from pathlib import Path

import pytest
import yaml

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import translator
from machine import load_sources, run_simulation

JOURNAL_HEAD = 30
JOURNAL_TAIL = 10


def trim_journal(messages: list) -> str:
    lines = []
    for message in messages:
        lines.extend(
            line.rstrip() for line in str(message).splitlines() if line.strip()
        )

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

    # Проверяем сам бинарник: листинг соответствует секции кода, а .data
    # берём из образа памяти, который действительно получит симулятор.
    image = bin_file.read_bytes()
    code_words = [
        int(line.split(" - ", 2)[1], 16) for line in listing_content.splitlines()
    ]
    code_end = len(code_words) * 4
    data_start = translator.DATA_SEGMENT_START
    data_end = translator.data_address_counter
    assert [
        word for (word,) in struct.iter_unpack(">I", image[:code_end])
    ] == code_words
    assert not any(image[code_end:data_start])
    assert not any(image[data_end:])
    data_dump = "\n".join(
        f"{data_start + index * 4:04d} - 0x{word:08X}"
        for index, (word,) in enumerate(
            struct.iter_unpack(">I", image[data_start:data_end])
        )
    )

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
    assert data_dump == golden.out["out_data_hex"]
    assert output == golden.out["out_stdout"]
    assert trim_journal(caplog.messages) == golden.out["out_log"]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("10-2-3", "10 2 - 3 -"),
        ("1 + 2 * 30", "1 2 30 * +"),
        ("(1 + 2) * 30", "1 2 + 30 *"),
        ("1+(2*3", "-1"),
        ("1 2", "-1"),
        ("1+", "-1"),
        ("1" * 33, "-1"),
    ],
)
def test_rpn_tokenization_and_validation(tmp_path, expression, expected):
    case = Path(__file__).with_name("golden") / "infix_to_rpn.yml"
    source = tmp_path / "rpn.lisp"
    binary = tmp_path / "rpn.bin"
    source.write_text(
        yaml.safe_load(case.read_text(encoding="utf-8"))["in_source"], encoding="utf-8"
    )
    translator.compile_file(str(source), str(binary))
    schedule = [(200 + 700 * i, ch) for i, ch in enumerate(expression + "\n")]
    output, _ = run_simulation(str(binary), schedule, max_ticks=120000)
    assert output == expected


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("0", "-1"),
        ("-5", "-1"),
        ("1", "0"),
        ("6", "8"),
        ("2147483648", "-1"),
        ("2147483647", "450"),
    ],
)
def test_collatz_input_and_wide_intermediates(tmp_path, number, expected):
    case = Path(__file__).with_name("golden") / "collatz.yml"
    source = tmp_path / "collatz.lisp"
    binary = tmp_path / "collatz.bin"
    source.write_text(
        yaml.safe_load(case.read_text(encoding="utf-8"))["in_source"], encoding="utf-8"
    )
    translator.compile_file(str(source), str(binary))
    schedule = [(200 + 1500 * i, ch) for i, ch in enumerate(number + "\n")]
    output, _ = run_simulation(str(binary), schedule, max_ticks=600000)
    assert output == expected
