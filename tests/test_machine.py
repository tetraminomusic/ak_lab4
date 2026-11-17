# tests/test_machine.py
import os
import struct
import sys

import pytest

# Добавляем путь к папке src

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import translator
from cache import Cache
from isa import Instruction, Opcode
from machine import ControlUnit, DataPath, load_input_schedule, run_simulation

# Задержки: промах = 10 тактов на блок из 4 слов, а попадание 1 такт


def test_cache_hit_and_miss_latencies():
    memory = [0] * 4096
    memory[25] = 42  # слово по байтовому адресу 100
    cache = Cache(memory, num_lines=8, block_size=4)

    val1, ticks1 = cache.read(100)
    assert val1 == 42
    assert ticks1 == 10
    assert cache.misses == 1
    assert cache.hits == 0

    val2, ticks2 = cache.read(100)
    assert val2 == 42
    assert ticks2 == 1
    assert cache.misses == 1
    assert cache.hits == 1


# Промах тянет весь блок, поэтому соседние адреса читаются уже из кеша.


def test_cache_block_gives_spatial_locality():
    memory = [0] * 4096
    for addr in (96, 100, 104, 108):
        memory[addr // 4] = addr

    cache = Cache(memory, num_lines=8, block_size=4)

    # Байтовые адреса лежат в одном блоке из 16 байт, мы платим только за первое обращение
    _, ticks = cache.read(96)
    assert ticks == 10

    for addr in (100, 104, 108):
        val, ticks = cache.read(addr)
        assert val == addr
        assert ticks == 1

    assert cache.misses == 1
    assert cache.hits == 3

    # Адрес 112 уже в следующем блоке, за него платим снова

    _, ticks = cache.read(112)
    assert ticks == 10


# Сквозная запись: пишет и в память, и обновляет строку кэша.


def test_cache_write_through():
    memory = [0] * 4096
    cache = Cache(memory, num_lines=8, block_size=4)

    cache.read(48)
    ticks = cache.write(48, 999)
    assert ticks == 10
    assert memory[12] == 999  # слово по байтовому адресу 48

    val, read_ticks = cache.read(48)
    assert val == 999
    assert read_ticks == 1


# Вытеснение кэша, то есть у нас 8 строк, 9 блок должен перезаписать 1


def test_cache_eviction():
    memory = [0] * 4096
    cache = Cache(memory, num_lines=8, block_size=4)

    # Заполняем все 8 строк кэша блоками 0..7
    for block in range(8):
        cache.read(block * 16)

    # Блок 8 ложится в строку и вытесняет блок 0
    cache.read(128)

    # Снова читаем адрес 0. Должен быть промах, строка была вытеснена
    _, ticks = cache.read(0)
    assert ticks == 10


def test_fetch_and_load_commit_when_memory_is_ready():
    dp = DataPath()
    dp.flag_z = 1

    cu = ControlUnit(dp)

    word = Instruction(Opcode.LD, ["R1", "R0", 128]).encode()
    dp.memory[0] = word
    dp.memory[32] = 123

    for _ in range(9):
        cu.tick()

    assert dp.cr == 0
    assert not cu.cache.lines[0].valid

    cu.tick()

    assert dp.cr == word
    assert cu.cache.lines[0].valid

    for _ in range(11):
        cu.tick()

    assert dp.read_reg("R1") == 0
    assert dp.pc == 0

    cu.tick()

    assert dp.read_reg("R1") == 123
    assert dp.pc == 4
    assert dp.flag_z == 1
    assert cu.instruction_counter == 1


def test_interrupt_during_store_wait_uses_next_instruction_boundary():
    dp = DataPath()
    dp.flag_ie = 1
    dp.write_reg("R1", 65)
    dp.memory[0] = Instruction(Opcode.ST, ["R1", "R0", 128]).encode()
    cu = ControlUnit(dp, schedule=[(14, "X")])

    for _ in range(21):
        cu.tick()

    assert dp.memory[32] == 0
    assert dp.pc == 0

    cu.tick()

    assert dp.memory[32] == 65
    assert dp.pc == 4

    cu.tick()

    assert cu.int_active
    assert not dp.flag_ie
    assert dp.memory[-1] == 0
    for _ in range(9):
        cu.tick()

    assert dp.memory[-1] == 4
    assert dp.memory[-2] == 0
    for _ in range(10):
        cu.tick()

    assert dp.memory[-2] & (1 << 5)
    assert dp.sp == 16372
    assert cu.instruction_counter == 1


def test_iret_checks_for_both_words_before_popping():
    dp = DataPath()
    dp.memory[0] = Instruction(Opcode.IRET).encode()
    dp.sp -= 4
    sp_before = dp.sp
    cu = ControlUnit(dp)
    for _ in range(20):
        cu.tick()
    assert cu.is_halted
    assert dp.sp == sp_before


@pytest.mark.parametrize(
    ("opcode", "args", "message"),
    [
        (Opcode.LD, ["R1", "R0", 1], "Невыровненный адрес"),
        (Opcode.IN, ["R1", 1], "Недопустимый порт IN"),
        (Opcode.OUT, [0, "R1"], "Недопустимый порт OUT"),
    ],
)
def test_invalid_machine_operands_stop_execution(caplog, opcode, args, message):
    dp = DataPath()
    dp.memory[0] = Instruction(opcode, args).encode()
    cu = ControlUnit(dp)
    for _ in range(30):
        cu.tick()
    assert cu.is_halted
    assert cu.instruction_counter == 0
    assert message in caplog.text


def test_hlt_stops_without_changing_processor_status():
    dp = DataPath()
    dp.flag_z = 1
    dp.flag_ie = 1
    status_before = dp.status_register
    assert status_before & (1 << 8) == 0
    dp.memory[0] = Instruction(Opcode.HLT).encode()

    cu = ControlUnit(dp)
    for _ in range(20):
        cu.tick()
        if cu.is_halted:
            break

    assert cu.is_halted
    assert dp.status_register == status_before
    tick_after_halt = cu.current_tick
    cu.tick()
    assert cu.current_tick == tick_after_halt


def test_instruction_log_decodes_third_register():
    word = Instruction(Opcode.ADD, ["R1", "R2", "R3"]).encode()
    assert str(Instruction.decode(word)) == "ADD R1, R2, R3"


def test_text_input_preserves_line_ending(tmp_path):
    path = tmp_path / "input.txt"
    path.write_text(" []\n", encoding="utf-8")

    assert load_input_schedule(path) == [
        (50, " "),
        (1550, "["),
        (3050, "]"),
        (4550, "\n"),
    ]


def test_json_input_uses_explicit_ticks(tmp_path):
    path = tmp_path / "input.json"
    path.write_text('[[100, "A"], [101, 42]]', encoding="utf-8")
    assert load_input_schedule(path) == [(100, "A"), (101, 42)]


def test_schedule_is_sorted_without_mutating_input():
    schedule = [(5, "B"), (0, "A")]
    dp = DataPath()
    ControlUnit(dp, schedule=schedule)
    assert dp.in_reg == ord("A")
    assert schedule == [(5, "B"), (0, "A")]


@pytest.mark.parametrize("image", [b"", b"\0", b"\0" * 16388])
def test_invalid_binary_image_is_rejected(tmp_path, image):
    binary = tmp_path / "program.bin"
    binary.write_bytes(image)
    with pytest.raises(ValueError, match="Бинарник должен содержать"):
        run_simulation(str(binary), [])


@pytest.mark.parametrize(
    ("word", "error"),
    [
        (0xFF000000, "Неизвестный код операции"),
        (0x02100001, "Невыровненный адрес"),
        (0x18000000, "недостаточно слов"),
    ],
)
def test_machine_fault_is_reported_to_cli(tmp_path, monkeypatch, capsys, word, error):
    from machine import main  # noqa: PLC0415

    binary = tmp_path / "program.bin"
    binary.write_bytes(struct.pack(">I", word))
    monkeypatch.setattr(sys, "argv", ["machine.py", "-c", str(binary)])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert error in capsys.readouterr().err


# Проверка выставления флагов NZCV


def test_alu_flags_nzcv():
    dp = DataPath()

    # Флаг Z
    dp.execute_alu(Opcode.SUB, 10, 10)
    assert dp.flag_z == 1
    assert dp.flag_n == 0

    # Флаг N
    dp.execute_alu(Opcode.SUB, 5, 10)
    assert dp.flag_n == 1
    assert dp.flag_z == 0

    # Флаг C
    dp.execute_alu(Opcode.ADD, 0xFFFFFFFF, 1)
    assert dp.flag_c == 1

    # Флаг V
    dp.execute_alu(Opcode.ADD, 0x7FFFFFFF, 1)
    assert dp.flag_v == 1


# Защита от деления на ноль в АЛУ


def test_alu_division_by_zero():
    dp = DataPath()
    res = dp.execute_alu(Opcode.DIV, 100, 0)
    assert res == 0


# Регистр R0 невозможно перезаписать


def test_r0_hardwired_zero():
    dp = DataPath()
    dp.write_reg("R0", 999)
    assert dp.read_reg("R0") == 0


# Тест выполнения арифметических инструкций процессором


def test_arithmetic_execution(tmp_path):
    source_file = tmp_path / "math.lisp"
    bin_file = tmp_path / "math.bin"

    source_file.write_text(
        """
    (progn
        (setq res (- (+ 65 5) 4))
        (out 1 res)
    )
    """,
        encoding="utf-8",
    )

    translator.compile_file(str(source_file), str(bin_file))
    output, _ = run_simulation(str(bin_file), schedule=[], max_ticks=300)
    assert output == "B"


# Тест рекурсии с аккумулятором (Tail Recursion) через аппаратный стек.


def test_functions_and_recursion_execution(tmp_path):
    source_file = tmp_path / "fact.lisp"
    bin_file = tmp_path / "fact.bin"

    source_file.write_text(
        """
    (progn
        (defun sum (n acc)
            (if (<= n 0)
                acc
                (sum (- n 1) (+ acc n))))

        (setq ans (sum 3 60))
        (out 1 ans)
    )
    """,
        encoding="utf-8",
    )

    translator.compile_file(str(source_file), str(bin_file))
    output, _ = run_simulation(str(bin_file), schedule=[], max_ticks=2000)
    assert output == "B"


# Тест чтения строки через команду aref


def test_pascal_string_traversal_with_aref(tmp_path):
    source_file = tmp_path / "str.lisp"
    bin_file = tmp_path / "str.bin"

    source_file.write_text(
        """
    (progn
        (setq s "OK")
        (out 1 (aref s 1))
        (out 1 (aref s 2))
    )
    """,
        encoding="utf-8",
    )

    translator.compile_file(str(source_file), str(bin_file))
    output, _ = run_simulation(str(bin_file), schedule=[], max_ticks=300)
    assert output == "OK"


# Стек должен расти вниз и выдерживать глубокую рекурсию.


def test_deep_recursion_stack_growth(tmp_path):
    source_file = tmp_path / "deep.lisp"
    bin_file = tmp_path / "deep.bin"

    source_file.write_text(
        """
    (progn
        (defun deep (n val)
            (if (<= n 0)
                val
                (deep (- n 1) val)))
        (out 1 (deep 15 65))
    )
    """,
        encoding="utf-8",
    )

    translator.compile_file(str(source_file), str(bin_file))
    output, _ = run_simulation(str(bin_file), schedule=[], max_ticks=8000)
    assert output == "A"


# Если буфер порта 0 пуст, чтение возвращает 0


def test_input_buffer_empty():
    dp = DataPath()
    cu = ControlUnit(dp)

    # 0x1B100000 = IN R1, 0
    dp.memory[0] = 0x1B100000

    while cu.instruction_counter == 0 and not cu.is_halted:
        cu.tick()

    assert dp.read_reg("R1") == 0


def test_interrupt_preserves_registers_across_function_call(tmp_path):
    source_file = tmp_path / "isr.lisp"
    bin_file = tmp_path / "isr.bin"
    source_file.write_text(
        """
        (progn
            (defun helper () (+ 1 2 3))
            (definterrupt isr () (progn (in 0) (helper)))
            (ei)
            (defun wait () (wait))
            (wait))
        """,
        encoding="utf-8",
    )

    translator.compile_file(str(source_file), str(bin_file))
    dp = DataPath()

    dp.memory[:] = [word for (word,) in struct.iter_unpack(">I", bin_file.read_bytes())]
    cu = ControlUnit(dp, schedule=[(220, "X")])
    for _ in range(219):
        cu.tick()

    dp.write_reg("R2", 65)
    before = dp.registers.copy()
    entered = False
    for _ in range(600):
        cu.tick()
        if entered and not cu.int_active:
            break

        entered |= cu.int_active

    assert entered
    assert not cu.int_active
    assert dp.registers == before


@pytest.mark.parametrize(
    ("source_text", "expected"),
    [
        ("(progn (> (print 65) (print 66)) (<= (print 67) (print 68)))", "ABCD"),
        (
            (
                "(progn (setq a 67) (defun id (x) x) "
                "(defun f (a) (progn (id (setq a 66)) (print a))) (f 65) (print a))"
            ),
            "BC",
        ),
        ("(progn (defun _start (x) x) (defun R1 () 65) (print (_start (R1))))", "A"),
    ],
)
def test_lisp_evaluation_semantics(tmp_path, source_text, expected):
    source = tmp_path / "test.lisp"
    binary = tmp_path / "test.bin"
    source.write_text(source_text, encoding="utf-8")
    translator.compile_file(str(source), str(binary))
    output, _ = run_simulation(str(binary), [], max_ticks=1000)
    assert output == expected


# Остановка симулятора по превышению лимита тактов


def test_timeout_execution(tmp_path):
    source_file = tmp_path / "inf.lisp"
    bin_file = tmp_path / "inf.bin"

    source_file.write_text(
        """
    (progn
        (defun inf () (inf))
        (inf)
    )
    """,
        encoding="utf-8",
    )

    translator.compile_file(str(source_file), str(bin_file))
    _, ticks = run_simulation(str(bin_file), schedule=[], max_ticks=150)
    assert ticks == 150


# Хвостовая рекурсия на 2000 витков не должна переполнять стек


def test_tail_recursion_does_not_grow_stack(tmp_path):
    source_file = tmp_path / "tail.lisp"
    bin_file = tmp_path / "tail.bin"

    source_file.write_text(
        """
    (progn
        (defun deep (n val)
            (if (<= n 0)
                val
                (deep (- n 1) val)))
        (out 1 (deep 2000 65))
    )
    """,
        encoding="utf-8",
    )

    translator.compile_file(str(source_file), str(bin_file))
    output, _ = run_simulation(str(bin_file), schedule=[], max_ticks=500000)
    assert output == "A"


# С выключенным кешем любое обращение в память стоит 10 тактов


def test_cache_can_be_disabled():
    memory = [0] * 4096
    memory[25] = 42  # слово по байтовому адресу 100
    cache = Cache(memory, num_lines=8, enabled=False)

    val1, ticks1 = cache.read(100)
    assert val1 == 42
    assert ticks1 == 10

    val2, ticks2 = cache.read(100)
    assert val2 == 42
    assert ticks2 == 10
    assert cache.hits == 0
