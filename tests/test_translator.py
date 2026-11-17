# tests/test_translator.py
import os
import sys

import pytest

# Добавляем папку src в путь поиска
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import translator
from isa import Opcode
from parser import StringLiteral, parse, tokenize


@pytest.fixture(autouse=True)
def reset_translator():
    translator.program = []
    translator.symbol_table = {}
    translator.data_memory = {}
    translator.functions = {}
    translator.local_vars = {}
    translator.current_reg = 1
    translator.label_counter = 0
    translator.data_address_counter = 100
    translator.interrupt_handler = None


# Забытая закрывающая скобка


def test_unclosed_parenthesis():
    code = "(+ 1 (* 2 3)"
    with pytest.raises(SyntaxError, match="Ожидалась закрывающая скобка"):
        parse(tokenize(code))


# Лишняя закрывающая скобка.


def test_extra_closing_parenthesis():
    code = "(+ 1 2) )"
    tokens = tokenize(code)
    parse(tokens)  # спарсили (+ 1 2)
    with pytest.raises(SyntaxError, match="Неожиданная закрывающая скобка"):
        parse(tokens)  # наткнулись на лишнюю )


# Точка с запятой внутри строки в кавычках не должна считаться комментарием.


def test_semicolon_inside_string():
    code = '(setq text "hello;world")'
    tokens = tokenize(code)
    ast = parse(tokens)
    assert isinstance(ast[2], StringLiteral)
    assert ast[2].text == "hello;world"


def test_comment_without_space_before_semicolon():
    assert parse(tokenize("(+ 1; comment\n 2)")) == ["+", 1, 2]


def test_unclosed_string():
    with pytest.raises(SyntaxError, match="закрывающая кавычка"):
        tokenize('(print "abc)')


def test_compile_rejects_trailing_expression(tmp_path):
    source = tmp_path / "source.lisp"
    source.write_text("(print 65) (print 66)", encoding="utf-8")

    with pytest.raises(SyntaxError, match="лишние токены"):
        translator.compile_file(str(source), str(tmp_path / "out.bin"))


def test_compile_rejects_ei_without_handler(tmp_path):
    source = tmp_path / "source.lisp"
    source.write_text("(ei)", encoding="utf-8")

    with pytest.raises(SyntaxError, match="нужен обработчик"):
        translator.compile_file(str(source), str(tmp_path / "out.bin"))


@pytest.mark.parametrize("code", ["(in 1)", "(out 0 65)"])
def test_ports_respect_direction(code):

    with pytest.raises(ValueError, match="только порт"):
        translator.compile_expr(parse(tokenize(code)))


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("(print (if 0 65 (ei)))", "не возвращает значения"),
        ("(definterrupt isr (x) (in 0))", "не должно быть аргументов"),
        ("(ei 1)", "не принимает аргументы"),
        ("(inc 1 2)", "требует один аргумент"),
    ],
)
def test_invalid_forms_are_rejected(code, error):
    with pytest.raises(SyntaxError, match=error):
        translator.compile_expr(parse(tokenize(code)))


def test_pascal_string_rejects_multibyte_characters():
    with pytest.raises(ValueError, match="ASCII"):
        translator.allocate_pstr("ёж")


# Пустая строка Pascal должна иметь длину 0


def test_empty_string_literal():
    code = '(setq empty "")'
    ast = parse(tokenize(code))
    translator.compile_expr(ast)
    # Переменная заняла адрес 100, строка легла следом: длина 0 по адресу 104
    assert translator.data_memory[104] == 0


# Глубокая вложенность скобок


def test_deeply_nested_expressions():
    code = "(+ 1 (+ 2 (+ 3 (+ 4 5))))"
    ast = parse(tokenize(code))
    res_reg = translator.compile_expr(ast)
    assert (
        res_reg == "R1"
    )  # Благодаря освобождению регистров всё должно свернуться в R1 пупупу


# Девочки и мальчики, сладкие, как карамельки А на них большие башмаки, это бар-бар-бар-барики Лёгкие, как мотыльки, а в глазах горят фонарики А на них большие башмаки, это барбарики


def test_if_with_variable_predicate():

    code = """
    (progn
        (setq p 1)
        (setq a (if p 10 20))
    )
    """
    ast = parse(tokenize(code))
    translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    # Проверяем, что сгенерировалась команда сравнения переменной с нулем R0

    cmp_with_zero = [
        instr
        for instr in clean_code
        if instr.opcode == Opcode.CMP and "R0" in instr.args
    ]
    assert len(cmp_with_zero) == 1, "Ожидалось сравнение переменной p с нулем R0"

    # Проверяем, что для перехода в else используется команда JZ

    jz_jumps = [instr for instr in clean_code if instr.opcode == Opcode.JZ]
    assert len(jz_jumps) == 1, "Ожидался прыжок в else по команде JZ"


def test_if_with_number_literal_predicate():
    code = "(if 1 100 200)"

    ast = parse(tokenize(code))
    _ = translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    # Условие-число должно сравниться с нулем и сгенерировать JZ

    assert Opcode.CMP in [instr.opcode for instr in clean_code]
    assert Opcode.JZ in [instr.opcode for instr in clean_code]
    assert clean_code[-1].opcode == Opcode.HLT


def test_variadic_addition():
    code = "(+ 1 2 3 4 5)"

    ast = parse(tokenize(code))
    res_reg = translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    # Должно сгенерироваться 4 инструкции ADD

    adds = [instr for instr in clean_code if instr.opcode == Opcode.ADD]
    assert len(adds) == 4
    assert res_reg == "R1"


def test_binary_op_wrong_arity():
    code = "(- 1 2 3)"
    ast = parse(tokenize(code))
    with pytest.raises(SyntaxError, match="требует ровно 2 операнда"):
        translator.compile_expr(ast)


# Aref должен генерировать ADD и LD из памяти.


def test_aref_read_pascal_string():
    code = """
    (progn
        (setq s "ITMO")
        (setq len (aref s 0))    ; чтение длины
        (setq char (aref s 1))   ; чтение первого символа
    )
    """
    ast = parse(tokenize(code))
    translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    # Проверяем, что сгенерировались инструкции LD для чтения со смещением

    loads = [instr for instr in clean_code if instr.opcode == Opcode.LD]
    assert len(loads) >= 2


# Aset должен вычислять адрес через ADD и записывать значение через ST


def test_aset_modify_memory():
    code = """
    (progn
        (setq s "ABC")
        (aset s 1 88) ; заменяем символ по индексу 1 на код 88 ('X')
    )
    """
    ast = parse(tokenize(code))
    translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    stores = [instr for instr in clean_code if instr.opcode == Opcode.ST]
    assert len(stores) >= 2  # запись переменной и запись через aset


# Проверка адресной карты векторов


def test_definterrupt_and_vector_table_linking():

    code = """
    (progn
        (definterrupt on_key ()
            (out 1 (in 0)))

        (setq x 100)
    )
    """
    ast = parse(tokenize(code))
    translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    # Адрес 0 обязан быть безусловным прыжком JMP на начало программы

    assert clean_code[0].opcode == Opcode.JMP

    # Адрес 1 обязан быть прыжком JMP на обработчик прерывания
    assert clean_code[1].opcode == Opcode.JMP

    # В коде обязана присутствовать инструкция возврата из прерывания IRET

    assert Opcode.IRET in [instr.opcode for instr in clean_code]


# Если definterrupt не объявлен, по адресу 0001 должна стоять заглушка IRET.


def test_vector_table_fallback_iret():
    code = "(setq a 42)"

    ast = parse(tokenize(code))
    translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    assert clean_code[0].opcode == Opcode.JMP
    assert clean_code[1].opcode == Opcode.IRET


def test_interrupt_handler_cannot_capture_function_argument():
    code = "(defun f (arg) (progn (definterrupt handler () (print arg)) 0))"
    ast = parse(tokenize(code))
    translator.collect_function_signatures(ast)
    with pytest.raises(NameError, match="необъявленной переменной: 'arg'"):
        translator.compile_expr(ast)


# Команда print expr должна выводить значение в порт 1 и возвращать его


def test_print_builtin():
    code = "(print 65)"
    ast = parse(tokenize(code))
    res_reg = translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    # Проверяем наличие команды OUT в порт 1

    out_instrs = [i for i in clean_code if i.opcode == Opcode.OUT and i.args[0] == 1]
    assert len(out_instrs) == 1
    assert res_reg == "R1"


# Проверка генерации машинных команд INC и DEC.


def test_inc_and_dec_opcodes():
    code = """
    (progn
        (setq a 10)
        (setq b (inc a))
        (setq c (dec b))
    )
    """
    ast = parse(tokenize(code))
    translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    opcodes = {i.opcode for i in clean_code}
    assert Opcode.INC in opcodes
    assert Opcode.DEC in opcodes


# Валидация количества аргументов у aref и aset


def test_aref_and_aset_syntax_errors():
    parse_tree = parse(tokenize("(aref s)"))
    with pytest.raises(SyntaxError, match="Команда 'aref' требует 2 аргумента"):
        translator.compile_expr(parse_tree)

    parse_tree = parse(tokenize("(aset s 1)"))
    with pytest.raises(SyntaxError, match="Команда 'aset' требует 3 аргумента"):
        translator.compile_expr(parse_tree)


# Хвостовой самовызов должен превратиться в JMP, а не в CALL


def test_tail_recursion_compiles_to_jump():
    code = """
    (progn
        (defun count (n)
            (if (= n 0)
                0
                (count (- n 1))))
        (count 5)
    )
    """
    ast = parse(tokenize(code))
    translator.collect_function_signatures(ast)
    translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    calls = [instr for instr in clean_code if instr.opcode == Opcode.CALL]
    assert len(calls) == 1, "Остаться должен только вызов из основной программы"


# Вызов не в хвостовой позиции оптимизировать нельзя, он остаётся CALL


def test_non_tail_recursion_keeps_call():
    code = """
    (progn
        (defun fact (n)
            (if (<= n 1)
                1
                (* n (fact (- n 1)))))
        (fact 3)
    )
    """
    ast = parse(tokenize(code))
    translator.collect_function_signatures(ast)
    translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    calls = [instr for instr in clean_code if instr.opcode == Opcode.CALL]
    assert len(calls) == 2, "Рекурсивный вызов внутри (* n ...) должен остаться вызовом"


# Сравнение вне условия должно давать 1 или 0, а не ошибку трансляции


def test_comparison_as_value():
    code = "(setq flag (= 1 1))"
    ast = parse(tokenize(code))
    res_reg = translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    assert res_reg is not None

    # Сравнение разворачивается в CMP, условный переход и две загрузки константы

    assert Opcode.CMP in [instr.opcode for instr in clean_code]
    assert Opcode.JNZ in [instr.opcode for instr in clean_code]


# В условии if сравнение остаётся переходом и не превращается в 1/0


def test_if_does_not_materialize_condition():
    code = "(if (= 1 2) 10 20)"
    ast = parse(tokenize(code))
    translator.compile_expr(ast)
    clean_code = translator.link_program(translator.program)

    # Одно сравнение и один условный переход, лишних загрузок единицы нет

    assert len([i for i in clean_code if i.opcode == Opcode.CMP]) == 1
    assert len([i for i in clean_code if i.opcode == Opcode.JNZ]) == 1
