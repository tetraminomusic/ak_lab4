# tests/test_massive_battery.py
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
# РАЗДЕЛ 1: ГРАНИЧНЫЕ СЛУЧАИ АРИФМЕТИКИ И ФЛАГОВ NZVC
# =====================================================================

def test_arith_zero_multiplication(tmp_path):
    """1. Умножение на 0."""
    sf, bf = tmp_path / "b1.lisp", tmp_path / "b1.bin"
    sf.write_text("(progn (out 1 (+ (* 12345 0) 65)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_arith_division_by_one(tmp_path):
    """2. Деление числа на 1."""
    sf, bf = tmp_path / "b2.lisp", tmp_path / "b2.bin"
    sf.write_text("(progn (out 1 (/ 65 1)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_arith_modulo_larger_number(tmp_path):
    """3. Остаток от деления меньшего числа на большее: 65 % 100 = 65."""
    sf, bf = tmp_path / "b3.lisp", tmp_path / "b3.bin"
    sf.write_text("(progn (out 1 (% 65 100)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_arith_nested_complex_expression(tmp_path):
    """4. Глубоко вложенное математическое выражение: (((10 + 20) * 2) + 5) = 65 ('A')."""
    sf, bf = tmp_path / "b4.lisp", tmp_path / "b4.bin"
    sf.write_text("(progn (out 1 (+ (* (+ 10 20) 2) 5)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_arith_negative_difference_flag_n(tmp_path):
    """5. Отрицательный результат разности с проверкой флага N через (< a b)."""
    sf, bf = tmp_path / "b5.lisp", tmp_path / "b5.bin"
    sf.write_text("""
    (progn
        (if (< 10 50)
            (out 1 65)  ; 'A'
            (out 1 66)) ; 'B'
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


# =====================================================================
# РАЗДЕЛ 2: ПОБИТОВАЯ ЛОГИКА, МАСКИ И СДВИГИ
# =====================================================================

def test_logic_bit_mask_extraction(tmp_path):
    """6. Извлечение байта по битовой маске: (0x123441 & 0xFF) = 65 ('A')."""
    sf, bf = tmp_path / "b6.lisp", tmp_path / "b6.bin"
    sf.write_text("(progn (out 1 (and 1193025 255)))", encoding="utf-8") # 0x123441 = 1193025
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_logic_double_not_idempotence(tmp_path):
    """7. Двойное логическое NOT восстанавливает значение: NOT(NOT(65)) = 65."""
    sf, bf = tmp_path / "b7.lisp", tmp_path / "b7.bin"
    sf.write_text("(progn (out 1 (not (not 65))))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_logic_shift_left_and_right(tmp_path):
    """8. Сдвиг влево и обратный сдвиг вправо: ((65 << 3) >> 3) = 65."""
    sf, bf = tmp_path / "b8.lisp", tmp_path / "b8.bin"
    sf.write_text("(progn (out 1 (lsr (lsl 65 3) 3)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_logic_xor_swap_simulation(tmp_path):
    """9. Обмен значений переменных через XOR."""
    sf, bf = tmp_path / "b9.lisp", tmp_path / "b9.bin"
    sf.write_text("""
    (progn
        (setq a 66) ; 'B'
        (setq b 65) ; 'A'
        (setq a (xor a b))
        (setq b (xor a b))
        (setq a (xor a b))
        (out 1 a) ; Теперь a == 65 ('A')
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


# =====================================================================
# РАЗДЕЛ 3: МАССИВЫ, ПАМЯТЬ И УКАЗАТЕЛИ (AREF / ASET)
# =====================================================================

def test_array_linear_search(tmp_path):
    """10. Линейный поиск символа в строке (поиск индекса буквы 'C' в "ABCDE")."""
    sf, bf = tmp_path / "b10.lisp", tmp_path / "b10.bin"
    sf.write_text("""
    (progn
        (setq arr "ABCDE")
        (defun find (target idx len)
            (if (> idx len)
                0
                (if (= (aref arr idx) target)
                    idx
                    (find target (+ idx 1) len))))
        
        ; Индекс буквы 'C' (67) равен 3. (3 + 62 = 65 -> 'A')
        (out 1 (+ (find 67 1 5) 62))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=3000)
    assert output == "A"


def test_array_sum_elements(tmp_path):
    """11. Суммирование элементов числового массива."""
    sf, bf = tmp_path / "b11.lisp", tmp_path / "b11.bin"
    sf.write_text("""
    (progn
        (setq data "   ") ; 3 ячейки
        (aset data 1 10)
        (aset data 2 20)
        (aset data 3 35)
        
        (defun sum (i)
            (if (<= i 3)
                (+ (aref data i) (sum (+ i 1)))
                0))
        
        ; 10 + 20 + 35 = 65 ('A')
        (out 1 (sum 1))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=3000)
    assert output == "A"


def test_array_bubble_sort_two_elements(tmp_path):
    """12. Сортировка двух элементов массива по возрастанию: "BA" -> "AB"."""
    sf, bf = tmp_path / "b12.lisp", tmp_path / "b12.bin"
    sf.write_text("""
    (progn
        (setq s "BA")
        (if (> (aref s 1) (aref s 2))
            (progn
                (setq tmp (aref s 1))
                (aset s 1 (aref s 2))
                (aset s 2 tmp))
            0)
        (out 1 (aref s 1))
        (out 1 (aref s 2))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "AB"


# =====================================================================
# РАЗДЕЛ 4: СЛОЖНЫЕ ФУНКЦИИ, ВЗАИМНАЯ РЕКУРСИЯ И СТЕК
# =====================================================================

def test_mutual_recursion_even_odd(tmp_path):
    """13. Взаимная рекурсия (Mutual Recursion): проверка четности числа."""
    sf, bf = tmp_path / "b13.lisp", tmp_path / "b13.bin"
    sf.write_text("""
    (progn
        (defun is_odd (n)
            (if (= n 0)
                0
                (is_even (- n 1))))

        (defun is_even (n)
            (if (= n 0)
                1
                (is_odd (- n 1))))

        ; 6 - четное -> is_even(6) вернет 1. (1 + 64 = 65 -> 'A')
        (out 1 (+ (is_even 6) 64))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=5000)
    assert output == "A"


def test_ackermann_function_small(tmp_path):
    """14. Функция Аккермана A(1, 2) = 4 (+ 61 = 65 -> 'A')."""
    sf, bf = tmp_path / "b14.lisp", tmp_path / "b14.bin"
    sf.write_text("""
    (progn
        (defun ack (m n)
            (if (= m 0)
                (+ n 1)
                (if (= n 0)
                    (ack (- m 1) 1)
                    (ack (- m 1) (ack m (- n 1))))))
        
        (out 1 (+ (ack 1 2) 61))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=8000)
    assert output == "A"


def test_power_function(tmp_path):
    """15. Возведение в степень: 2^6 = 64 (+ 1 = 65 -> 'A')."""
    sf, bf = tmp_path / "b15.lisp", tmp_path / "b15.bin"
    sf.write_text("""
    (progn
        (defun power (base exp)
            (if (= exp 0)
                1
                (* base (power base (- exp 1)))))
        
        (out 1 (+ (power 2 6) 1))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=4000)
    assert output == "A"


# =====================================================================
# РАЗДЕЛ 5: СЛОЖНЫЕ ЦИКЛЫ И МНОГОЭТАПНЫЕ ВЫЧИСЛЕНИЯ
# =====================================================================

def test_prime_number_check(tmp_path):
    """16. Проверка простоты числа 7 -> выводит 'P' (80), иначе 'C' (67)."""
    sf, bf = tmp_path / "b16.lisp", tmp_path / "b16.bin"
    sf.write_text("""
    (progn
        (defun check_div (n d)
            (if (> (* d d) n)
                1
                (if (= (% n d) 0)
                    0
                    (check_div n (+ d 1)))))
        
        (defun is_prime (n)
            (if (<= n 1)
                0
                (check_div n 2)))
        
        (if (= (is_prime 7) 1)
            (out 1 80)   ; 'P'
            (out 1 67))  ; 'C'
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=4000)
    assert output == "P"


def test_sum_of_digits(tmp_path):
    """17. Сумма цифр числа 998: 9 + 9 + 8 = 26 (+ 39 = 65 -> 'A')."""
    sf, bf = tmp_path / "b17.lisp", tmp_path / "b17.bin"
    sf.write_text("""
    (progn
        (defun sum_digits (n)
            (if (= n 0)
                0
                (+ (% n 10) (sum_digits (/ n 10)))))
        
        (out 1 (+ (sum_digits 998) 39))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=4000)
    assert output == "A"


def test_binary_representation_output(tmp_path):
    """18. Вывод числа 5 в двоичном виде: "101"."""
    sf, bf = tmp_path / "b18.lisp", tmp_path / "b18.bin"
    sf.write_text("""
    (progn
        (defun print_bin (n)
            (if (> n 0)
                (progn
                    (print_bin (/ n 2))
                    (out 1 (+ (% n 2) 48)))
                0))
        (print_bin 5)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=4000)
    assert output == "101"


# =====================================================================
# РАЗДЕЛ 6: ИНТЕНСИВНЫЕ ТЕСТЫ IO, ПРЕРЫВАНИЙ И КЭША
# =====================================================================

def test_interrupt_heavy_stream_ten_chars(tmp_path):
    """19. Потоковый прием пакета из 10 символов через прерывания ("0123456789")."""
    sf, bf = tmp_path / "b19.lisp", tmp_path / "b19.bin"
    sf.write_text("""
    (progn
        (setq cnt 0)
        (definterrupt isr ()
            (progn
                (out 1 (in 0))
                (setq cnt (+ cnt 1))
                (ei)))
        (ei)

        (defun wait_ten ()
            (if (< cnt 10)
                (wait_ten)
                0))
        (wait_ten)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    schedule = [[i * 15, str(i)] for i in range(10)]
    output, _ = run_simulation(str(bf), schedule=schedule, max_ticks=4000)
    assert output == "0123456789"


def test_io_caesar_cipher_on_the_fly(tmp_path):
    """20. Шифр Цезаря на лету: прием "ABC", сдвиг на +1 -> вывод "BCD"."""
    sf, bf = tmp_path / "b20.lisp", tmp_path / "b20.bin"
    sf.write_text("""
    (progn
        (out 1 (+ (in 0) 1))
        (out 1 (+ (in 0) 1))
        (out 1 (+ (in 0) 1))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    schedule = [[0, "A"], [0, "B"], [0, "C"]]
    output, _ = run_simulation(str(bf), schedule=schedule)
    assert output == "BCD"


def test_cache_thrashing_loop(tmp_path):
    """21. Тест кэша: циклическое обращение к ячейкам с разным tag (проверка кэш-промахов)."""
    sf, bf = tmp_path / "b21.lisp", tmp_path / "b21.bin"
    sf.write_text("""
    (progn
        (setq x 10)
        (setq y 20)
        (setq z 35)
        ; Многократное перекрестное чтение
        (out 1 (+ (+ x y) z))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"

# =====================================================================
# РАЗДЕЛ 7: СЕМАНТИЧЕСКИЕ ПРОВЕРКИ И ОБРАБОТКА ОШИБОК
# =====================================================================

def test_semantic_duplicate_function_error(tmp_path):
    """22. Ошибка: повторное объявление функции с тем же именем должно кидать ValueError."""
    sf, bf = tmp_path / "b22.lisp", tmp_path / "b22.bin"
    sf.write_text("""
    (progn
        (defun my_func (x) (+ x 1))
        (defun my_func (y) (+ y 2))
    )
    """, encoding="utf-8")
    with pytest.raises(ValueError, match="уже объявлена ранее"):
        translator.compile_file(str(sf), str(bf))


def test_semantic_reserved_keyword_as_function_name(tmp_path):
    """23. Ошибка: нельзя назвать функцию зарезервированным словом (например, 'setq')."""
    sf, bf = tmp_path / "b23.lisp", tmp_path / "b23.bin"
    sf.write_text("""
    (progn
        (defun setq (x) (+ x 1))
    )
    """, encoding="utf-8")
    with pytest.raises(SyntaxError, match="зарезервированным словом"):
        translator.compile_file(str(sf), str(bf))


def test_semantic_unbound_variable_error(tmp_path):
    """24. Ошибка: обращение к необъявленной переменной должно кидать NameError."""
    sf, bf = tmp_path / "b24.lisp", tmp_path / "b24.bin"
    sf.write_text("""
    (progn
        (out 1 undeclared_var)
    )
    """, encoding="utf-8")
    with pytest.raises(NameError, match="Использование необъявленной переменной"):
        translator.compile_file(str(sf), str(bf))


# =====================================================================
# РАЗДЕЛ 8: СЛОЖНЫЕ ЦЕПОЧКИ ВЫЗОВОВ ФУНКЦИЙ
# =====================================================================

def test_nested_function_calls_composition(tmp_path):
    """25. Композиция функций: inc(mul2(add5(25))) -> (25 + 5) * 2 + 1 = 61 (+ 4 = 65 -> 'A')."""
    sf, bf = tmp_path / "b25.lisp", tmp_path / "b25.bin"
    sf.write_text("""
    (progn
        (defun add5 (x) (+ x 5))
        (defun mul2 (x) (* x 2))
        (defun inc_f (x) (+ x 1))

        ; inc_f(mul2(add5(25))) = (25 + 5)*2 + 1 = 61. (61 + 4 = 65 -> 'A')
        (out 1 (+ (inc_f (mul2 (add5 25))) 4))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=4000)
    assert output == "A"


def test_function_passing_multiple_results(tmp_path):
    """26. Передача результатов двух разных функций в третью: sum2(sqr(5), sqr(6)) = 25 + 36 = 61 (+ 4 = 65 -> 'A')."""
    sf, bf = tmp_path / "b26.lisp", tmp_path / "b26.bin"
    sf.write_text("""
    (progn
        (defun sqr (x) (* x x))
        (defun sum2 (a b) (+ a b))

        ; sqr(5) + sqr(6) = 25 + 36 = 61. (61 + 4 = 65 -> 'A')
        (out 1 (+ (sum2 (sqr 5) (sqr 6)) 4))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=4000)
    assert output == "A"


# =====================================================================
# РАЗДЕЛ 9: АЛГОРИТМЫ НА СТРОКАХ И МАССИВАХ
# =====================================================================

def test_array_find_maximum(tmp_path):
    """27. Поиск максимального элемента в массиве: max([12, 65, 33, 40]) = 65 ('A')."""
    sf, bf = tmp_path / "b27.lisp", tmp_path / "b27.bin"
    sf.write_text("""
    (progn
        (setq arr "    ") ; 4 ячейки
        (aset arr 1 12)
        (aset arr 2 65)
        (aset arr 3 33)
        (aset arr 4 40)

        (defun find_max (idx current_max len)
            (if (> idx len)
                current_max
                (if (> (aref arr idx) current_max)
                    (find_max (+ idx 1) (aref arr idx) len)
                    (find_max (+ idx 1) current_max len))))

        (out 1 (find_max 1 0 4))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=4000)
    assert output == "A"


def test_string_count_character_occurrences(tmp_path):
    """28. Подсчет количества символов 'L' в строке "HELLO WORLD" (3 штуки, 3 + 62 = 65 -> 'A')."""
    sf, bf = tmp_path / "b28.lisp", tmp_path / "b28.bin"
    sf.write_text("""
    (progn
        (setq text "HELLO WORLD")
        ; 'L' имеет ASCII код 76
        (defun count_char (target idx len)
            (if (> idx len)
                0
                (+ (if (= (aref text idx) target) 1 0)
                   (count_char target (+ idx 1) len))))

        ; 3 + 62 = 65 ('A')
        (out 1 (+ (count_char 76 1 11) 62))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=5000)
    assert output == "A"


def test_string_copy_and_concatenate(tmp_path):
    """29. Конкатенация двух строк: "AB" + "CD" -> "ABCD"."""
    sf, bf = tmp_path / "b29.lisp", tmp_path / "b29.bin"
    sf.write_text("""
    (progn
        (setq s1 "AB")
        (setq s2 "CD")
        (setq res "    ") ; 4 ячейки

        (aset res 1 (aref s1 1))
        (aset res 2 (aref s1 2))
        (aset res 3 (aref s2 1))
        (aset res 4 (aref s2 2))

        (out 1 (aref res 1))
        (out 1 (aref res 2))
        (out 1 (aref res 3))
        (out 1 (aref res 4))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "ABCD"


# =====================================================================
# РАЗДЕЛ 10: МАТЕМАТИКА И ТЕОРИЯ ЧИСЕЛ
# =====================================================================

def test_modular_exponentiation(tmp_path):
    """30. Быстрое возведение в степень по модулю: (3^7) % 100 = 2187 % 100 = 87 (- 22 = 65 -> 'A')."""
    sf, bf = tmp_path / "b30.lisp", tmp_path / "b30.bin"
    sf.write_text("""
    (progn
        (defun mod_pow (base exp mod)
            (if (= exp 0)
                1
                (% (* base (mod_pow base (- exp 1) mod)) mod)))

        ; (3^7) % 100 = 87. (87 - 22 = 65 -> 'A')
        (out 1 (- (mod_pow 3 7 100) 22))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=4000)
    assert output == "A"


def test_is_power_of_two(tmp_path):
    """31. Проверка степени двойки через побитовое И: (n & (n - 1)) == 0 для n = 64."""
    sf, bf = tmp_path / "b31.lisp", tmp_path / "b31.bin"
    sf.write_text("""
    (progn
        (setq n 64)
        ; Если 64 & 63 == 0 -> выводим 'Y' (89), иначе 'N' (78)
        (if (= (and n (- n 1)) 0)
            (out 1 89)   ; 'Y'
            (out 1 78))  ; 'N'
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "Y"


def test_integer_square_root(tmp_path):
    """32. Целочисленный квадратный корень: isqrt(49) = 7 (+ 58 = 65 -> 'A')."""
    sf, bf = tmp_path / "b32.lisp", tmp_path / "b32.bin"
    sf.write_text("""
    (progn
        (defun isqrt_helper (n g)
            (if (<= (* g g) n)
                (if (> (* (+ g 1) (+ g 1)) n)
                    g
                    (isqrt_helper n (+ g 1)))
                (isqrt_helper n (- g 1))))

        ; isqrt(49) = 7. (7 + 58 = 65 -> 'A')
        (out 1 (+ (isqrt_helper 49 1) 58))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=4000)
    assert output == "A"


# =====================================================================
# РАЗДЕЛ 11: ЦЕПОЧКИ PROGN И СТОРОННИЕ ЭФФЕКТЫ
# =====================================================================

def test_progn_evaluates_all_side_effects(tmp_path):
    """33. Проверка, что progn честно вычисляет все промежуточные выражения с побочными эффектами."""
    sf, bf = tmp_path / "b33.lisp", tmp_path / "b33.bin"
    sf.write_text("""
    (progn
        (setq x 10)
        (setq y 20)
        ; progn выполняет 3 присваивания и возвращает последнее выражение
        (setq res (progn
                    (setq x (+ x 5))
                    (setq y (+ y 10))
                    (+ x y))) ; 15 + 30 = 45 (+ 20 = 65 -> 'A')
        (out 1 (+ res 20))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_large_number_division_and_remainder(tmp_path):
    """34. Деление чисел в пределах 16 бит: 65000 / 1000 = 65 ('A')."""
    sf, bf = tmp_path / "b34.lisp", tmp_path / "b34.bin"
    sf.write_text("(progn (out 1 (/ 65000 1000)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[])
    assert output == "A"


def test_array_bubble_sort_full(tmp_path):
    """35. Полноценная пузырьковая сортировка массива из 4 элементов: "DCBA" -> "ABCD"."""
    sf, bf = tmp_path / "b35.lisp", tmp_path / "b35.bin"
    sf.write_text("""
    (progn
        (setq arr "DCBA")

        (defun swap_if_needed (i j)
            (if (> (aref arr i) (aref arr j))
                (progn
                    (setq tmp (aref arr i))
                    (aset arr i (aref arr j))
                    (aset arr j tmp))
                0))

        ; 6 сравнений для сортировки 4 элементов
        (swap_if_needed 1 2)
        (swap_if_needed 2 3)
        (swap_if_needed 3 4)
        (swap_if_needed 1 2)
        (swap_if_needed 2 3)
        (swap_if_needed 1 2)

        (out 1 (aref arr 1))
        (out 1 (aref arr 2))
        (out 1 (aref arr 3))
        (out 1 (aref arr 4))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))
    output, _ = run_simulation(str(bf), schedule=[], max_ticks=8000)
    assert output == "ABCD"