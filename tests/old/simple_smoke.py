# tests/test_simple_smoke.py
import sys
import os
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from isa import Opcode, Instruction
import translator
from machine import DataPath, ControlUnit, run_simulation
from cache import Cache

@pytest.fixture(autouse=True)
def reset_all():
    translator.program = []
    translator.symbol_table = {}
    translator.data_memory = {}
    translator.functions = {}
    translator.local_vars = {}
    translator.current_reg = 1
    translator.label_counter = 0
    translator.data_address_counter = 1000
    translator.interrupt_handler = None


# =====================================================================
# БЛОК 1: ТЕСТЫ АРИФМЕТИКИ И МАТЕМАТИКИ
# =====================================================================

def test_simple_addition(tmp_path):
    """1. Простейшее сложение двух чисел."""
    sf, bf = tmp_path / "t1.lisp", tmp_path / "t1.bin"
    sf.write_text("(progn (out 1 (+ 20 30)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    # 20 + 30 = 50 (ASCII код 50 — это цифра '2', код 50 в char — нет, 50 это '2' в ASCII? Нет, ASCII 50 это '2'. 
    # Пардон, лучше складывать до символов ASCII, например (+ 60 5) = 65 ('A')
    # Но для теста проверим значение в памяти или выведем код 65 ('A')


def test_ascii_output_A(tmp_path):
    """2. Вывод символа 'A' (ASCII 65)."""
    sf, bf = tmp_path / "t2.lisp", tmp_path / "t2.bin"
    sf.write_text("(progn (out 1 65))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_subtraction(tmp_path):
    """3. Вычитание: 70 - 5 = 65 ('A')."""
    sf, bf = tmp_path / "t3.lisp", tmp_path / "t3.bin"
    sf.write_text("(progn (out 1 (- 70 5)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_multiplication(tmp_path):
    """4. Умножение: 13 * 5 = 65 ('A')."""
    sf, bf = tmp_path / "t4.lisp", tmp_path / "t4.bin"
    sf.write_text("(progn (out 1 (* 13 5)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_division(tmp_path):
    """5. Деление: 130 / 2 = 65 ('A')."""
    sf, bf = tmp_path / "t5.lisp", tmp_path / "t5.bin"
    sf.write_text("(progn (out 1 (/ 130 2)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_modulo(tmp_path):
    """6. Остаток от деления: 165 % 100 = 65 ('A')."""
    sf, bf = tmp_path / "t6.lisp", tmp_path / "t6.bin"
    sf.write_text("(progn (out 1 (% 165 100)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_variadic_addition(tmp_path):
    """7. Сложение трех чисел: 60 + 3 + 2 = 65 ('A')."""
    sf, bf = tmp_path / "t7.lisp", tmp_path / "t7.bin"
    sf.write_text("(progn (out 1 (+ 60 3 2)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_inc_operation(tmp_path):
    """8. Операция инкремента: (inc 64) = 65 ('A')."""
    sf, bf = tmp_path / "t8.lisp", tmp_path / "t8.bin"
    sf.write_text("(progn (out 1 (inc 64)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_dec_operation(tmp_path):
    """9. Операция декремента: (dec 66) = 65 ('A')."""
    sf, bf = tmp_path / "t9.lisp", tmp_path / "t9.bin"
    sf.write_text("(progn (out 1 (dec 66)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


# =====================================================================
# БЛОК 2: ПЕРЕМЕННЫЕ И ПАМЯТЬ (SETQ)
# =====================================================================

def test_variable_assignment(tmp_path):
    """10. Запись в переменную и чтение из неё."""
    sf, bf = tmp_path / "t10.lisp", tmp_path / "t10.bin"
    sf.write_text("""
    (progn
        (setq x 65)
        (out 1 x)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_variable_as_expression(tmp_path):
    """11. Использование setq внутри математики."""
    sf, bf = tmp_path / "t11.lisp", tmp_path / "t11.bin"
    sf.write_text("""
    (progn
        (out 1 (+ (setq x 60) 5))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


# =====================================================================
# БЛОК 3: УСЛОВНЫЕ ПЕРЕХОДЫ И СРАВНЕНИЯ (IF)
# =====================================================================

def test_if_equals_true(tmp_path):
    """12. Условие равно (=): истина."""
    sf, bf = tmp_path / "t12.lisp", tmp_path / "t12.bin"
    sf.write_text("(progn (if (= 10 10) (out 1 65) (out 1 66)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_if_equals_false(tmp_path):
    """13. Условие равно (=): ложь."""
    sf, bf = tmp_path / "t13.lisp", tmp_path / "t13.bin"
    sf.write_text("(progn (if (= 10 20) (out 1 65) (out 1 66)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "B"


def test_if_less_than(tmp_path):
    """14. Сравнение меньше (<)."""
    sf, bf = tmp_path / "t14.lisp", tmp_path / "t14.bin"
    sf.write_text("(progn (if (< 5 10) (out 1 65) (out 1 66)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_if_greater_than(tmp_path):
    """15. Сравнение больше (> через перестановку операндов)."""
    sf, bf = tmp_path / "t15.lisp", tmp_path / "t15.bin"
    sf.write_text("(progn (if (> 15 10) (out 1 65) (out 1 66)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_if_variable_predicate(tmp_path):
    """16. Предикат-переменная в if: (if p 65 66)."""
    sf, bf = tmp_path / "t16.lisp", tmp_path / "t16.bin"
    sf.write_text("""
    (progn
        (setq p 1)
        (out 1 (if p 65 66))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


# =====================================================================
# БЛОК 4: СТРОКИ И МАССИВЫ (PSTR, AREF, ASET)
# =====================================================================

def test_pstr_length_via_aref(tmp_path):
    """17. Проверка длины Pascal-строки через aref по индексу 0."""
    sf, bf = tmp_path / "t17.lisp", tmp_path / "t17.bin"
    sf.write_text("""
    (progn
        (setq s "ABCD") ; длина 4
        ; Прибавим 61 к длине (4 + 61 = 65 -> 'A')
        (out 1 (+ (aref s 0) 61))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_aset_array_modification(tmp_path):
    """18. Запись в массив/строку через aset и чтение через aref."""
    sf, bf = tmp_path / "t18.lisp", tmp_path / "t18.bin"
    sf.write_text("""
    (progn
        (setq s "XYZ")
        (aset s 1 65) ; меняем 'X' (индекс 1) на 65 ('A')
        (out 1 (aref s 1))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"

def test_debug_func_args(tmp_path):
    """Тест 1: передача двух аргументов в функцию."""
    sf, bf = tmp_path / "dbg1.lisp", tmp_path / "dbg1.bin"
    sf.write_text("""
    (progn
        (defun sub_ab (a b) (- a b))
        (out 1 (sub_ab 70 5))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"  # 70 - 5 = 65 ('A')

def test_debug_port_input(tmp_path):
    """Тест 2: чтение из порта на 0-м такте."""
    sf, bf = tmp_path / "dbg2.lisp", tmp_path / "dbg2.bin"
    sf.write_text("(progn (out 1 (in 0)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[(5, 'A')])
    assert output == "A"

def test_debug_interrupt(tmp_path):
    """Тест 3: обработка прерывания."""
    sf, bf = tmp_path / "dbg3.lisp", tmp_path / "dbg3.bin"
    sf.write_text("""
    (progn
        (definterrupt my_isr ()
            (out 1 (in 0)))
        (ei)
        ; Небольшой цикл ожидания
        (setq x 0)
        (if (= x 0) (setq x 1) 0)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[(5, 'Z')])
    assert output == "Z"