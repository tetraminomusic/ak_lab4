# tests/test_translator.py
import sys
import os
import pytest

# Добавляем папку src в путь поиска
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from parser import tokenize, parse, StringLiteral
from isa import Opcode
import translator


@pytest.fixture(autouse=True)
def reset_translator():
    """Сброс состояния перед каждым тестом."""
    translator.program = []
    translator.symbol_table = {}
    translator.data_memory = {}
    translator.functions = {}
    translator.local_vars = {}
    translator.current_reg = 1
    translator.label_counter = 0
    translator.data_address_counter = 100

def test_unclosed_parenthesis():
    """Ошибка: забытая закрывающая скобка."""
    code = "(+ 1 (* 2 3)"
    with pytest.raises(SyntaxError, match="Ожидалась закрывающая скобка"):
        parse(tokenize(code))


def test_extra_closing_parenthesis():
    """Ошибка: лишняя закрывающая скобка."""
    code = "(+ 1 2) )"
    tokens = tokenize(code)
    parse(tokens)  # спарсили (+ 1 2)
    with pytest.raises(SyntaxError, match="Неожиданная закрывающая скобка"):
        parse(tokens)  # наткнулись на лишнюю ')'


def test_semicolon_inside_string():
    """Точка с запятой внутри строки в кавычках НЕ должна считаться комментарием."""
    code = '(setq text "hello;world")'
    tokens = tokenize(code)
    ast = parse(tokens)
    assert isinstance(ast[2], StringLiteral)
    assert ast[2].text == "hello;world"


def test_empty_string_literal():
    """Пустая строка Pascal должна иметь длину 0."""
    code = '(setq empty "")'
    ast = parse(tokenize(code))
    translator.compile_expr(ast)
    # По адресу 101 должна лежать длина 0
    assert translator.data_memory[101] == 0


def test_deeply_nested_expressions():
    """Глубокая вложенность скобок (в пределах лимита регистров)."""
    code = "(+ 1 (+ 2 (+ 3 (+ 4 5))))"
    ast = parse(tokenize(code))
    res_reg = translator.compile_expr(ast)
    assert res_reg == "R1"  # Благодаря освобождению регистров всё должно свернуться в R1

def test_all_bitwise_and_shift_operations():
    """Проверка генерации всех битовых и сдвиговых инструкций."""
    code = """
    (progn
        (setq a (and 1 2))
        (setq b (or 3 4))
        (setq c (xor 5 6))
        (setq d (not 7))
        (setq e (lsl 8 1))
        (setq f (lsr 9 1))
        (setq g (rol 10 1))
        (setq h (ror 11 1))
        (setq i (asr 12 1))
        (setq j (% 13 2))
    )
    """
    ast = parse(tokenize(code))
    translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    opcodes = {instr.opcode for instr in clean_code}
    expected_opcodes = {
        Opcode.AND, Opcode.OR, Opcode.XOR, Opcode.NOT,
        Opcode.LSL, Opcode.LSR, Opcode.ROL, Opcode.ROR,
        Opcode.ASR, Opcode.MOD
    }
    assert expected_opcodes.issubset(opcodes)
