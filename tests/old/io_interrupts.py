# tests/test_io_interrupts.py
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
    """Сброс состояния транслятора перед каждым тестом."""
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
# БЛОК 1: БАЗОВЫЙ И СИНХРОННЫЙ ВВОД/ВЫВОД (POLLING)
# =====================================================================

def test_io_direct_single_char(tmp_path):
    """1. Прямое чтение одного символа из порта 0 и вывод в порт 1."""
    sf, bf = tmp_path / "io1.lisp", tmp_path / "io1.bin"
    sf.write_text("(progn (out 1 (in 0)))", encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    output, _ = run_simulation(str(bf), schedule=[[0, "A"]])
    assert output == "A"


def test_io_stream_sequential(tmp_path):
    """2. Последовательное чтение трех символов подряд (потоковый ввод)."""
    sf, bf = tmp_path / "io2.lisp", tmp_path / "io2.bin"
    sf.write_text("""
    (progn
        (out 1 (in 0))
        (out 1 (in 0))
        (out 1 (in 0))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    schedule = [[0, "H"], [0, "E"], [0, "Y"]]
    output, _ = run_simulation(str(bf), schedule=schedule)
    assert output == "HEY"


def test_io_read_into_variable(tmp_path):
    """3. Чтение из порта в переменную, инкремент и вывод."""
    sf, bf = tmp_path / "io3.lisp", tmp_path / "io3.bin"
    sf.write_text("""
    (progn
        (setq ch (in 0))         ; Считываем 'A' (код 65)
        (out 1 (+ ch 1))         ; Выводим 65 + 1 = 66 ('B')
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    output, _ = run_simulation(str(bf), schedule=[[0, "A"]])
    assert output == "B"


def test_io_empty_buffer_returns_zero(tmp_path):
    """4. Чтение из пустого порта должно возвращать 0."""
    sf, bf = tmp_path / "io4.lisp", tmp_path / "io4.bin"
    sf.write_text("""
    (progn
        (setq ch (in 0))
        ; Если прочитали 0 — выводим 'Z' (код 90), иначе 'E'
        (if (= ch 0)
            (out 1 90)
            (out 1 69))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    output, _ = run_simulation(str(bf), schedule=[])  # Пустой ввод
    assert output == "Z"


# =====================================================================
# БЛОК 2: АППАРАТНЫЕ ПРЕРЫВАНИЯ (INTERRUPTS & ISR)
# =====================================================================

def test_interrupt_basic_reception(tmp_path):
    """5. Базовое прерывание: переход на ISR, чтение и возврат по IRET."""
    sf, bf = tmp_path / "io5.lisp", tmp_path / "io5.bin"
    sf.write_text("""
    (progn
        (definterrupt isr_handler ()
            (out 1 (in 0)))
        (ei)
        ; Полезная нагрузка процессора до прерывания
        (setq counter 0)
        (setq counter (+ counter 1))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    # Прерывание приходит на 10-м такте
    output, _ = run_simulation(str(bf), schedule=[[10, "K"]])
    assert output == "K"


def test_interrupt_preserves_main_registers(tmp_path):
    """6. Прерывание не должно ломать логику и регистры основной программы."""
    sf, bf = tmp_path / "io6.lisp", tmp_path / "io6.bin"
    sf.write_text("""
    (progn
        (definterrupt isr_handler ()
            (out 1 (in 0)))
        (ei)
        ; Основной поток вычисляет число 65 ('A')
        (setq a 60)
        (setq b 5)
        (out 1 (+ a b))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    # Прерывание присылает '!', основная программа должна допечатать 'A' -> "!A"
    output, _ = run_simulation(str(bf), schedule=[[5, "!"]])
    assert output == "!A"


def test_interrupt_disabled_by_di(tmp_path):
    """7. Команда DI (Disable Interrupts) должна блокировать вызов ISR."""
    sf, bf = tmp_path / "io7.lisp", tmp_path / "io7.bin"
    sf.write_text("""
    (progn
        (definterrupt isr_handler ()
            (out 1 (in 0)))
        (di) ; Запрещаем прерывания
        (out 1 65) ; Печатаем 'A'
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    # Символ 'X' приходит, но прерывание заблокировано -> на выходе только 'A'
    output, _ = run_simulation(str(bf), schedule=[[5, "X"]])
    assert output == "A"


def test_multiple_interrupts_in_time(tmp_path):
    """8. Обработка двух последовательных прерываний в разное время."""
    sf, bf = tmp_path / "io8.lisp", tmp_path / "io8.bin"
    sf.write_text("""
    (progn
        (definterrupt isr_handler ()
            (progn
                (out 1 (in 0))
                (ei))) ; Разрешаем следующее прерывание
        (ei)
        (setq x 0)
        (setq x (+ x 1))
        (setq x (+ x 1))
        (setq x (+ x 1))
        (setq x (+ x 1))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    schedule = [[5, "1"], [50, "2"]]
    output, _ = run_simulation(str(bf), schedule=schedule, max_ticks=500)
    assert output == "12"


# =====================================================================
# БЛОК 3: ПРОДВИНУТЫЕ СЦЕНАРИИ IO И ПРЕРЫВАНИЙ
# =====================================================================

def test_interrupt_preserves_alu_flags(tmp_path):
    """9. Прерывание не должно сбивать флаги NZVC основного потока."""
    sf, bf = tmp_path / "io9.lisp", tmp_path / "io9.bin"
    sf.write_text("""
    (progn
        (definterrupt isr ()
            ; Обработчик выполняет операцию, сбрасывающую флаг Z (например, 10 - 5)
            (progn
                (in 0)
                (- 10 5)))
        (ei)
        ; Основной поток делает операцию, дающую Z = 1 (10 - 10 = 0)
        (setq x (- 10 10))
        ; Если флаг Z сохранился после прерывания -> выведет 'A' (65), иначе 'B' (66)
        (if (= x 0)
            (out 1 65)
            (out 1 66))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    # Прерывание срабатывает прямо перед проверкой if
    output, _ = run_simulation(str(bf), schedule=[[20, "!"]])
    assert output == "A"


def test_io_buffer_to_memory_and_print(tmp_path):
    """10. Запись входящих символов в массив и последующий вывод строки."""
    sf, bf = tmp_path / "io10.lisp", tmp_path / "io10.bin"
    sf.write_text("""
    (progn
        (setq buf "   ") ; Выделяем буфер под 3 символа
        (aset buf 1 (in 0))
        (aset buf 2 (in 0))
        (aset buf 3 (in 0))
        
        ; Выводим обратно из памяти
        (out 1 (aref buf 1))
        (out 1 (aref buf 2))
        (out 1 (aref buf 3))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    schedule = [[0, "O"], [0, "K"], [0, "!"]]
    output, _ = run_simulation(str(bf), schedule=schedule)
    assert output == "OK!"


def test_interrupt_during_loop(tmp_path):
    """11. Прерывание во время активного цикла (хвостовой рекурсии)."""
    sf, bf = tmp_path / "io11.lisp", tmp_path / "io11.bin"
    sf.write_text("""
    (progn
        (setq intr_done 0)
        (definterrupt on_char ()
            (progn
                (out 1 (in 0))
                (setq intr_done 1)))
        (ei)
        
        ; Крутимся в цикле, пока прерывание не установит intr_done = 1
        (defun wait_for_interrupt ()
            (if (= intr_done 0)
                (wait_for_interrupt)
                (out 1 65))) ; После выхода из цикла допечатываем 'A'
        
        (wait_for_interrupt)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    # На такте 40 прилетает '7', затем цикл завершается и допечатывает 'A'
    output, _ = run_simulation(str(bf), schedule=[[40, "7"]], max_ticks=1000)
    assert output == "7A"


def test_critical_section_toggle_ei_di(tmp_path):
    """12. Критическая секция: прерывание игнорируется во время DI, но принимается после EI."""
    sf, bf = tmp_path / "io12.lisp", tmp_path / "io12.bin"
    sf.write_text("""
    (progn
        (definterrupt isr ()
            (out 1 (in 0)))
        
        ; Запрещаем прерывания на время критической секции
        (di)
        (setq x 100)
        (setq x (+ x 50))
        
        ; Открываем прерывания после критической секции
        (ei)
        
        ; Небольшая задержка, чтобы прерывание успело обработаться
        (setq y 0)
        (if (= y 0) (out 1 65) 0)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    # Символ приходит на 5 такте (когда действует DI), но обрабатывается позже при EI
    output, _ = run_simulation(str(bf), schedule=[[5, "Q"]])
    assert output == "QA"


def test_fast_consecutive_interrupts(tmp_path):
    """13. Очередь быстрых прерываний (пакет из 4 символов)."""
    sf, bf = tmp_path / "io13.lisp", tmp_path / "io13.bin"
    sf.write_text("""
    (progn
        (setq count 0)
        (definterrupt isr ()
            (progn
                (out 1 (in 0))
                (setq count (+ count 1))
                (ei))) ; Разрешаем следующее прерывание
        (ei)
        
        ; Крутимся в цикле, пока не примем ровно 4 символа
        (defun wait_for_all ()
            (if (< count 4)
                (wait_for_all)
                0))
        (wait_for_all)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    schedule = [[5, "R"], [25, "I"], [45, "S"], [65, "C"]]
    output, _ = run_simulation(str(bf), schedule=schedule, max_ticks=1500)
    assert output == "RISC"

def test_null_terminated_input_stream(tmp_path):
    """14. Чтение потока символов до нулевого терминатора (0x00)."""
    sf, bf = tmp_path / "io14.lisp", tmp_path / "io14.bin"
    sf.write_text("""
    (progn
        (defun echo_until_null ()
            (progn
                (setq ch (in 0))
                (if (!= ch 0)
                    (progn
                        (out 1 ch)
                        (echo_until_null))
                    0)))
        (echo_until_null)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    # Передаем "GO" и завершающий 0
    schedule = [[0, "G"], [0, "O"], [0, 0], [0, "X"]]
    output, _ = run_simulation(str(bf), schedule=schedule)
    # 'X' не должен быть напечатан, так как цикл остановился на 0
    assert output == "GO"


# =====================================================================
# БЛОК 4: СТРЕСС-ТЕСТЫ И КРАЕВЫЕ СЛУЧАИ ПРЕРЫВАНИЙ
# =====================================================================

def test_interrupt_during_deep_stack(tmp_path):
    """15. Прерывание во время глубокого стека (вложенная рекурсия)."""
    sf, bf = tmp_path / "io15.lisp", tmp_path / "io15.bin"
    sf.write_text("""
    (progn
        (definterrupt isr ()
            (out 1 (in 0)))
        (ei)

        ; Глубокая рекурсия (глубина 5)
        (defun deep_call (depth)
            (if (> depth 0)
                (+ 1 (deep_call (- depth 1)))
                0))

        ; Вычисляем 60 + deep_call(5) = 65 ('A')
        (out 1 (+ 60 (deep_call 5)))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    # Прерывание прилетает на глубине стека
    output, _ = run_simulation(str(bf), schedule=[[35, "!"]], max_ticks=2000)
    assert output == "!A"


def test_interrupt_modifies_shared_variable(tmp_path):
    """16. Прерывание меняет глобальную переменную (счетчик событий)."""
    sf, bf = tmp_path / "io16.lisp", tmp_path / "io16.bin"
    sf.write_text("""
    (progn
        (setq hits 0)
        (definterrupt isr ()
            (progn
                (in 0)
                (setq hits (+ hits 1))
                (ei)))
        (ei)

        ; Основной поток делает холостую работу
        (setq i 0)
        (defun loop ()
            (if (< hits 3)
                (loop)
                0))
        (loop)

        ; Выводим количество обработанных прерываний: 3 + 65 = 68 ('D')
        (out 1 (+ hits 65))
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    schedule = [[10, "1"], [30, "2"], [50, "3"]]
    output, _ = run_simulation(str(bf), schedule=schedule, max_ticks=2000)
    assert output == "D"


def test_nested_interrupt_masking(tmp_path):
    """17. Защита от повторного прерывания: второе событие ждет завершения первого ISR."""
    sf, bf = tmp_path / "io17.lisp", tmp_path / "io17.bin"
    sf.write_text("""
    (progn
        (setq count 0)
        (definterrupt isr ()
            (progn
                (out 1 (in 0))
                (setq count (+ count 1))))
        (ei)

        (defun wait_for_two ()
            (if (< count 2)
                (wait_for_two)
                0))
        (wait_for_two)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    # Два прерывания приходят быстро: первое обрабатывается, второе ждет выхода по IRET
    schedule = [[10, "A"], [12, "B"]]
    output, _ = run_simulation(str(bf), schedule=schedule, max_ticks=800)
    assert output == "AB"


def test_interrupt_during_string_output(tmp_path):
    """18. Прерывание во время посимвольного вывода строки из памяти."""
    sf, bf = tmp_path / "io18.lisp", tmp_path / "io18.bin"
    sf.write_text("""
    (progn
        (definterrupt isr ()
            (out 1 (in 0)))
        (ei)

        (setq msg "HELLO")
        (defun print_str (idx len)
            (if (<= idx len)
                (progn
                    (out 1 (aref msg idx))
                    (print_str (+ idx 1) len))
                0))

        (print_str 1 5)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    # Прерывание вклинивается прямо между буквами
    output, _ = run_simulation(str(bf), schedule=[[30, "*"]], max_ticks=2000)
    assert output == "HE*LLO" or output == "H*ELLO" or "*" in output
    # Проверяем, что все буквы слова HELLO напечатаны и среди них есть звёздочка
    assert output.replace("*", "") == "HELLO"


def test_burst_input_in_single_tick(tmp_path):
    """19. Пакетный приход нескольких символов в один и тот же такт."""
    sf, bf = tmp_path / "io19.lisp", tmp_path / "io19.bin"
    sf.write_text("""
    (progn
        (definterrupt isr ()
            (progn
                (out 1 (in 0))
                (ei)))
        (ei)

        (setq n 0)
        (defun loop ()
            (if (< n 3)
                (loop)
                0))
        (loop)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    # Все 3 символа поступили ровно на такте 10
    schedule = [[10, "1"], [10, "2"], [10, "3"]]
    output, _ = run_simulation(str(bf), schedule=schedule, max_ticks=500)
    assert output == "123"


def test_interrupt_does_not_corrupt_stack_pointer(tmp_path):
    """20. Проверка целостности указателя стека SP после серии вызовов прерываний."""
    sf, bf = tmp_path / "io20.lisp", tmp_path / "io20.bin"
    sf.write_text("""
    (progn
        (definterrupt isr ()
            (progn
                (in 0)
                (out 1 65))) ; Печатаем 'A' на каждое прерывание
        (ei)

        ; Основной поток делает PUSH/POP через функции
        (defun dummy (x) (+ x 1))
        (dummy 10)
        (dummy 20)
        (dummy 30)
    )
    """, encoding="utf-8")
    translator.compile_file(str(sf), str(bf))

    schedule = [[5, "X"], [25, "Y"]]
    output, _ = run_simulation(str(bf), schedule=schedule, max_ticks=500)
    assert output == "AA"