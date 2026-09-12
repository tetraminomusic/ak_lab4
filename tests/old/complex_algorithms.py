# tests/test_complex_algorithms.py
import sys
import os
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from isa import Opcode, Instruction
import translator
from machine import DataPath, ControlUnit, run_simulation
from cache import Cache

@pytest.fixture(autouse=True)
def reset_translator():
    """Сброс состояния компилятора перед каждым тестом."""
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
# БЛОК 1: КЛАССИЧЕСКИЕ АЛГОРИТМЫ
# =====================================================================

def test_fibonacci_recursive(tmp_path):
    """1. Числа Фибоначчи через двойную рекурсию: fib(7) = 13 (+ 52 = 65 -> 'A')."""
    sf, bf = tmp_path / "alg1.lisp", tmp_path / "alg1.bin"
    sf.write_text("""
    (progn
        (defun fib (n)
            (if (<= n 1)
                n
                (+ (fib (- n 1)) (fib (- n 2)))))
        
        ; 13 + 52 = 65 ('A')
        (out 1 (+ (fib 7) 52))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=15000)
    assert output == "A"


def test_gcd_euclidean_algorithm(tmp_path):
    """2. Алгоритм Евклида (НОД): gcd(48, 18) = 6 (+ 59 = 65 -> 'A')."""
    sf, bf = tmp_path / "alg2.lisp", tmp_path / "alg2.bin"
    sf.write_text("""
    (progn
        (defun gcd (a b)
            (if (= b 0)
                a
                (gcd b (% a b))))
        
        ; 6 + 59 = 65 ('A')
        (out 1 (+ (gcd 48 18) 59))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=3000)
    assert output == "A"


def test_collatz_conjecture_steps(tmp_path):
    """3. Шаги гипотезы Коллатца для числа 6: 6->3->10->5->16->8->4->2->1 (8 шагов, 8 + 57 = 65 -> 'A')."""
    sf, bf = tmp_path / "alg3.lisp", tmp_path / "alg3.bin"
    sf.write_text("""
    (progn
        (defun collatz (n steps)
            (if (<= n 1)
                steps
                (if (= (% n 2) 0)
                    (collatz (/ n 2) (+ steps 1))
                    (collatz (+ (* 3 n) 1) (+ steps 1)))))
        
        ; 8 + 57 = 65 ('A')
        (out 1 (+ (collatz 6 0) 57))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=4000)
    assert output == "A"


# =====================================================================
# БЛОК 2: СТРОКИ И МАССИВЫ
# =====================================================================

def test_string_reverse_in_place(tmp_path):
    """4. Реверс строки в памяти: "RISC" -> "CSIR"."""
    sf, bf = tmp_path / "alg4.lisp", tmp_path / "alg4.bin"
    sf.write_text("""
    (progn
        (setq s "RISC")
        
        (defun rev (left right)
            (if (< left right)
                (progn
                    (setq temp (aref s left))
                    (aset s left (aref s right))
                    (aset s right temp)
                    (rev (+ left 1) (- right 1)))
                0))
        
        (rev 1 4)
        
        ; Выводим развернутую строку
        (out 1 (aref s 1))
        (out 1 (aref s 2))
        (out 1 (aref s 3))
        (out 1 (aref s 4))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=4000)
    assert output == "CSIR"


def test_palindrome_checker(tmp_path):
    """5. Проверка палиндрома "RADAR" -> выводит 'Y' (89), иначе 'N' (78)."""
    sf, bf = tmp_path / "alg5.lisp", tmp_path / "alg5.bin"
    sf.write_text("""
    (progn
        (setq pal "RADAR")
        
        (defun is_pal (l r)
            (if (>= l r)
                1
                (if (= (aref pal l) (aref pal r))
                    (is_pal (+ l 1) (- r 1))
                    0)))
        
        (if (= (is_pal 1 5) 1)
            (out 1 89)   ; 'Y'
            (out 1 78))  ; 'N'
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=3000)
    assert output == "Y"


def test_print_multi_digit_number(tmp_path):
    """6. Печать многозначного числа 12345 через деление на 10 и стек."""
    sf, bf = tmp_path / "alg6.lisp", tmp_path / "alg6.bin"
    sf.write_text("""
    (progn
        (defun print_num (n)
            (if (> n 0)
                (progn
                    (print_num (/ n 10))
                    ; Превращаем цифру в ASCII символ (+ 48)
                    (out 1 (+ (% n 10) 48)))
                0))
        
        (print_num 12345)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=5000)
    assert output == "12345"


# =====================================================================
# БЛОК 3: ИНТЕГРАЦИЯ АЛГОРИТМОВ С ПРЕРЫВАНИЯМИ
# =====================================================================

def test_interrupt_accumulate_sum_during_heavy_math(tmp_path):
    """7. Асинхронное накопление суммы чисел из порта прерываний во время тяжелых вычислений."""
    sf, bf = tmp_path / "alg7.lisp", tmp_path / "alg7.bin"
    sf.write_text("""
    (progn
        (setq total 0)
        (definterrupt isr ()
            (progn
                ; Прерывание читает цифру (1, 2, 3), вычитает код '0' (48) и прибавляет к total
                (setq val (- (in 0) 48))
                (setq total (+ total val))
                (ei)))
        (ei)

        ; Основной поток вычисляет факториал 5! = 120
        (defun fact (n)
            (if (<= n 1)
                1
                (* n (fact (- n 1)))))

        (setq res (fact 5))
        
        ; В конце печатаем накопленную сумму total (1 + 2 + 3 = 6 -> символ '6')
        (out 1 (+ total 48))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    # Прерывания прилетают во время вычисления факториала
    schedule = [[10, "1"], [30, "2"], [50, "3"]]
    output, _ = run_simulation(str(bf), schedule=schedule, max_ticks=4000)
    assert output == "6"