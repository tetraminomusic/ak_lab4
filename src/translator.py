import argparse
import struct
import sys
from pathlib import Path

from isa import INPUT_PORT, OUTPUT_PORT, WORD_SIZE, Instruction, Opcode
from parser import Node, StringLiteral, parse, tokenize

# Номер следующего свободного регистра при генерации команд.
current_reg = 1
# Счётчик для создания уникальных меток.
label_counter = 0
# Последний регистр, который выделяет транслятор.
LAST_COMPILER_REG = 10

# Байтовый адрес начала сегмента данных.
DATA_SEGMENT_START = 4000
# Граница между данными и областью стека.
STACK_LIMIT = 12400

# Следующий свободный байтовый адрес для размещения данных.
data_address_counter = DATA_SEGMENT_START

# Метка обработчика прерываний или None, если он не объявлен.
interrupt_handler: str | None = None

# Имя глобальной переменной -> её адрес.
symbol_table: dict[str, int] = {}
# Байтовый адрес -> начальное значение слова данных.
data_memory: dict[int, int] = {}
# Имя функции -> количество её аргументов.
functions: dict[str, int] = {}

# Имя параметра текущей функции -> закреплённый за ним регистр.
local_vars: dict[str, str] = {}

# Сгенерированные команды и символические метки до компоновки.
program: list[Instruction | str] = []

# Переходы, которые срабатывают при ложном сравнении в условии.
INVERSE_JUMPS = {
    "=": Opcode.JNZ,
    "!=": Opcode.JZ,
    "<": Opcode.JGE,
    ">=": Opcode.JL,
}

# Допустимые операции сравнения.
COMPARE_OPS = {"=", "!=", "<", "<=", ">", ">="}

BINARY_OPS = {
    "+",
    "-",
    "*",
    "/",
    "%",
    "and",
    "or",
    "xor",
    "lsl",
    "lsr",
    "<<",
    ">>",
}

RESERVED_KEYWORDS = {
    "ei",
    "di",
    "if",
    "defun",
    "setq",
    "progn",
    "+",
    "-",
    "*",
    "/",
    "%",
    "=",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
    "in",
    "out",
    "and",
    "or",
    "xor",
    "not",
    "lsl",
    "lsr",
    "<<",
    ">>",
    "inc",
    "dec",
    "print",
    "aref",
    "aset",
    "definterrupt",
}

# Предварительный проход
# Записывает имена функций с числом аргументов, дабы при последующей генерацией компилятор знал, существует ли вызываемая функция и скок аргументов для неё надо.


def collect_function_signatures(node: Node) -> None:
    if isinstance(node, list) and len(node) > 0:
        if node[0] == "defun" and len(node) == 4 and isinstance(node[2], list):
            func_name = node[1]
            arg_list = node[2]

            if not isinstance(func_name, str):
                raise TypeError(
                    f"Имя функции должно быть строкой, а получили: {func_name}",
                )

            if func_name in RESERVED_KEYWORDS:
                raise SyntaxError(
                    f"Нельзя назвать функцию зарезервированным словом '{func_name}'",
                )

            if func_name in functions:
                raise ValueError(
                    f'Функция с именем "{func_name}" уже объявлена ранее',
                )

            functions[func_name] = len(arg_list)

        for sub in node:
            collect_function_signatures(sub)


# Размещает Pascal строку в памяти данных и возвращает её начальный адрес. Возвращает адрес первого слова.


def allocate_pstr(text: str) -> int:
    global data_address_counter
    start_addr = data_address_counter
    if not text.isascii():
        raise ValueError("Pascal-строка допускает только однобайтовые ASCII-символы")

    data_memory[start_addr] = len(text)
    data_address_counter += WORD_SIZE

    for char in text:
        data_memory[data_address_counter] = ord(char)
        data_address_counter += WORD_SIZE

    return start_addr


# Возвращает адрес существующей переменной или выделяет новый адрес в памяти


def get_or_allocate_var(var_name: str) -> int:
    global data_address_counter
    if var_name not in symbol_table:
        symbol_table[var_name] = data_address_counter
        data_address_counter += WORD_SIZE
    return symbol_table[var_name]


# Выдает имя следующего свободного регистра, который мы можем использовать для рекурсивного кода


def allocate_reg() -> str:
    global current_reg

    if current_reg > LAST_COMPILER_REG:
        raise RuntimeError("Ошибка компилятора: свободных регистров нету")

    reg_name = f"R{current_reg}"
    current_reg += 1
    return reg_name


# Освобождает последний занятый регистр. Реализация простая как пять пальцев.


def free_reg() -> None:
    global current_reg
    current_reg -= 1


# Генерация команд для загрузки литерала в регистр. Тут обработка по канонам риска через загрузку двух частей 32 битного числа за раз. Если оно 16 ричное, то грузим так.


def load_constant(reg: str, value: int) -> None:
    value &= 0xFFFF_FFFF

    if value <= 0xFFFF:
        program.append(Instruction(Opcode.LDI, [reg, value]))
        return

    tmp_reg = allocate_reg()

    program.append(Instruction(Opcode.LDI, [reg, (value >> 16) & 0xFFFF]))
    program.append(Instruction(Opcode.LDI, [tmp_reg, 16]))
    program.append(Instruction(Opcode.LSL, [reg, reg, tmp_reg]))
    program.append(Instruction(Opcode.LDI, [tmp_reg, value & 0xFFFF]))
    program.append(Instruction(Opcode.OR, [reg, reg, tmp_reg]))

    free_reg()


# Нужен для aref и aset для обращения к памяти по байтовому адресу.


def scale_index(idx_reg: str) -> None:
    shift_reg = allocate_reg()

    program.append(Instruction(Opcode.LDI, [shift_reg, WORD_SIZE // 2]))
    program.append(Instruction(Opcode.LSL, [idx_reg, idx_reg, shift_reg]))

    free_reg()


# Компилирует выражение и требует, чтоб было возвращаемое значение, иначе выкенет ошибку.


def compile_value(node: Node) -> str:
    reg = compile_expr(node)

    if reg is None:
        raise SyntaxError(f"Выражение не возвращает значения: {node}")

    return reg


# Предварительный просмотр того, а какие регистры может затронуть обработчик прерываний. Эти инструкции нужно зарнее сохранить.


def collect_used_regs(instructions: list[Instruction | str]) -> list[int]:
    used = set()

    for item in instructions:
        if not isinstance(item, Instruction):
            continue

        # Вызванная функция может изменить регистры, которых нет в теле обработчика фан фект

        if item.opcode == Opcode.CALL:
            return list(range(1, LAST_COMPILER_REG + 1))

        # Тут просто проходимся циклом по всем аругментам и смотрим, какие регистры можем затронуть

        for arg in item.args:
            if isinstance(arg, str) and arg.startswith("R") and arg[1:].isdigit():
                idx = int(arg[1:])
                if idx != 0:
                    used.add(idx)

    return sorted(used)


# Компоновщик, нужный для замены символических меток на числовые адреса памяти


def link_program(raw_program: list[Instruction | str]) -> list[Instruction]:

    # Сначала разбираемся с таблицей векторов прерывания
    # В 0 адресе у нас будет просто JMP _start, только потом JMP на обработчик, либо IRET, если обработчика нет

    if interrupt_handler is None:
        interrupt_vector = Instruction(Opcode.IRET)
    else:
        interrupt_vector = Instruction(Opcode.JMP, [interrupt_handler])

    vector_table = [Instruction(Opcode.JMP, ["_start"]), interrupt_vector]

    full_program = [*vector_table, "_start:", *raw_program]

    # Первый проход: находим адреса всех меток и собираем чистый список команд

    labels_map: dict[str, int] = {}
    clean_instructions: list[Instruction] = []
    current_address = 0

    for item in full_program:
        if isinstance(item, str):
            label_name = item[:-1]
            labels_map[label_name] = current_address
        else:
            clean_instructions.append(item)
            current_address += WORD_SIZE

    # Второй проход: подставляем числовые адреса вместо текстовых

    for instr in clean_instructions:
        for i, arg in enumerate(instr.args):
            if isinstance(arg, str) and arg in labels_map:
                instr.args[i] = labels_map[arg]

    clean_instructions.append(Instruction(Opcode.HLT))

    return clean_instructions


# Создаёт уникальную метку, используется для условий и преобразования с командами ветвления


def make_label(prefix: str = "L") -> str:
    global label_counter
    name = f"{prefix}_{label_counter}"
    label_counter += 1
    return name


# Компилирует нужное условие сравнения под знак сравнения + генерирует команду CMP и возвращает опкод прыжка в else, если условие ложно


def compile_condition(condition_node: Node) -> Opcode:

    if (
        isinstance(condition_node, list)
        and len(condition_node) == 3
        and condition_node[0] in ("=", "!=", "<", "<=", ">", ">=")
    ):
        op = condition_node[0]
        left = condition_node[1]
        right = condition_node[2]

        reg_left = compile_value(left)
        reg_right = compile_value(right)
        if op in (">", "<="):
            program.append(Instruction(Opcode.CMP, [reg_right, reg_left]))
            jump = Opcode.JGE if op == ">" else Opcode.JL
        else:
            program.append(Instruction(Opcode.CMP, [reg_left, reg_right]))
            jump = INVERSE_JUMPS[op]
        free_reg()
        free_reg()
        return jump

    cond_reg = compile_value(condition_node)
    program.append(Instruction(Opcode.CMP, [cond_reg, "R0"]))
    free_reg()
    return Opcode.JZ


# Компилирует последнее действие функции, после которого она совершит возврат (хвостовая рекурсия крч)
# Если по простому, что функция оптимизирует рекурсию так, что последний вызов делается не через CALL, а через JMP


def compile_tail_body(
    node: Node,
    func_name: str,
    epilogue_label: str,
    result_reg: str,
) -> None:
    if isinstance(node, list) and len(node) > 0:
        # Если тело заканчивается формой progn, то тогда все выражения, кроме последнего, компилируются как обычные

        if node[0] == "progn" and len(node) > 1:
            for expr in node[1:-1]:
                if compile_expr(expr) is not None:
                    free_reg()
            compile_tail_body(node[-1], func_name, epilogue_label, result_reg)
            return

        # Если if, то вызываем отдельно для веток then и else хвостовой самовызов

        if node[0] == "if" and len(node) == 4:
            label_else = make_label("else")
            jump_to_else_op = compile_condition(node[1])
            program.append(Instruction(jump_to_else_op, [label_else]))

            compile_tail_body(node[2], func_name, epilogue_label, result_reg)

            program.append(f"{label_else}:")
            compile_tail_body(node[3], func_name, epilogue_label, result_reg)
            return

        # Вызов самой функции

        if node[0] == func_name and len(node) - 1 == functions.get(func_name, -1):
            temp_regs = [compile_value(arg) for arg in node[1:]]

            for i, temp_reg in enumerate(temp_regs):
                target_reg = f"R{i + 1}"
                if temp_reg != target_reg:
                    program.append(
                        Instruction(Opcode.ADD, [target_reg, temp_reg, "R0"]),
                    )

            for _ in temp_regs:
                free_reg()

            program.append(Instruction(Opcode.JMP, [f"fn:{func_name}"]))
            return

    value_reg = compile_value(node)
    program.append(Instruction(Opcode.ADD, [result_reg, value_reg, "R0"]))
    free_reg()

    program.append(Instruction(Opcode.JMP, [epilogue_label]))


# Превращение из узла дерева в читаемую запись языка Лисп, нужно для отладочного листа


def node_to_text(node: Node) -> str:
    if isinstance(node, list):
        return "(" + " ".join(node_to_text(item) for item in node) + ")"

    if isinstance(node, StringLiteral):
        return f'"{node.text}"'

    return str(node)


# Обрётка над compile_node, которая к новым командам добавляет эквивалент (не знаю как правильно назвать) команды на лиспе, опять таки, нужно для отладочного листа


def compile_expr(node: Node) -> str | None:
    start = len(program)
    result_reg = compile_node(node)
    text = node_to_text(node)

    for item in program[start:]:
        if isinstance(item, Instruction) and not item.source:
            item.source = text

    return result_reg


# Главная функция для трансляции из кода лисп в машинный


def compile_node(node: Node) -> str | None:
    global local_vars, current_reg, interrupt_handler, program

    # Проверяем, может это простое число

    if isinstance(node, int):
        reg = allocate_reg()
        load_constant(reg, node)
        return reg

    # Проверяем строковую переменную

    if isinstance(node, str):
        # Если это параметр текущей функции, то выделяем регистр для результата и копируем туда значение через ADD

        if node in local_vars:
            reg = allocate_reg()
            program.append(Instruction(Opcode.ADD, [reg, local_vars[node], "R0"]))
            return reg

        # Если это глобальная переменная, то просто генерим LDI и LD для косвенной адресации

        if node in symbol_table:
            addr = symbol_table[node]
            reg = allocate_reg()
            program.append(Instruction(Opcode.LDI, [reg, addr]))
            program.append(Instruction(Opcode.LD, [reg, reg, 0]))
            return reg

        raise NameError(f"Использование необъявленной переменной: '{node}'")

    # Проверяем строковый литерал, в регистр через LDI помещаем адрес начала строки

    if isinstance(node, StringLiteral):
        str_addr = allocate_pstr(node.text)
        reg = allocate_reg()
        program.append(Instruction(Opcode.LDI, [reg, str_addr]))
        return reg

    # Рекурсивный случай: списковое выражение

    if isinstance(node, list):
        if len(node) == 0:
            raise SyntaxError("Пустые скобки () не являются допустимым выражением")

        op = node[0]

        # Разрешение прерывания

        if op == "ei":
            if len(node) != 1:
                raise SyntaxError("Команда ei не принимает аргументы")
            program.append(Instruction(Opcode.EI))
            return None

        # Запрет прерывания

        if op == "di":
            if len(node) != 1:
                raise SyntaxError("Команда di не принимает аргументы")
            program.append(Instruction(Opcode.DI))
            return None

        # Чтение элемента массива по индексу

        if op == "aref":
            if len(node) != 3:
                raise SyntaxError(
                    "Команда 'aref' требует 2 аргумента: (aref массив индекс)",
                )

            base_expr = node[1]
            idx_expr = node[2]

            base_reg = compile_value(base_expr)
            idx_reg = compile_value(idx_expr)
            scale_index(idx_reg)

            # Тут базированно используем косвенную адресацию по база + индекс, короче изи пизи

            program.append(Instruction(Opcode.ADD, [base_reg, base_reg, idx_reg]))
            free_reg()

            program.append(Instruction(Opcode.LD, [base_reg, base_reg, 0]))
            return base_reg

        # Запись в массив/строку по индексу

        if op == "aset":
            if len(node) != 4:
                raise SyntaxError(
                    "Команда 'aset' требует 3 аргумента: (aset массив индекс значение)",
                )

            base_expr = node[1]
            idx_expr = node[2]
            val_expr = node[3]

            base_reg = compile_value(base_expr)
            idx_reg = compile_value(idx_expr)

            # Умножаем индекс на 4

            scale_index(idx_reg)
            val_reg = compile_value(val_expr)

            program.append(Instruction(Opcode.ADD, [base_reg, base_reg, idx_reg]))
            program.append(Instruction(Opcode.ST, [val_reg, base_reg, 0]))

            program.append(Instruction(Opcode.ADD, [base_reg, val_reg, "R0"]))

            free_reg()
            free_reg()
            return base_reg

        # Последовательное выполнение progn, где у первых выражений освобождаем регистры, а у последнего вызываем выполнения expr

        if op == "progn":
            last_reg = None
            for expr in node[1:]:
                if last_reg is not None:
                    free_reg()
                last_reg = compile_expr(expr)
            return last_reg

        # Объявление обработчика прерывания

        if op == "definterrupt":
            if len(node) != 4:
                raise SyntaxError(
                    "Конструкция definterrupt требует: (definterrupt имя () тело)",
                )

            handler_name = node[1]
            body_expr = node[3]

            if not isinstance(handler_name, str):
                raise TypeError(
                    f"Имя обработчика должно быть строкой, а получили: {handler_name}",
                )
            if node[2] != []:
                raise SyntaxError("У обработчика прерывания не должно быть аргументов")
            if interrupt_handler is not None:
                raise SyntaxError("Поддерживается один обработчик прерывания")

            interrupt_handler = f"isr:{handler_name}"

            label_skip = make_label(f"skip_intr_{handler_name}")

            # Ставим джамп, чтобы перепрыгнуть программу на всякий пожарный

            program.append(Instruction(Opcode.JMP, [label_skip]))
            program.append(f"{interrupt_handler}:")

            # Отдельно транслируем тело по новой с новыми регистрами

            outer_program = program
            program = []

            old_reg = current_reg
            old_locals = local_vars
            current_reg = 1
            local_vars = {}
            intr_res = compile_expr(body_expr)
            if intr_res is not None:
                free_reg()
            current_reg = old_reg
            local_vars = old_locals

            body = program
            program = outer_program

            # Сохраняем старые регистры, которые мы можем затереть случайно

            used_regs = collect_used_regs(body)

            for i in used_regs:
                program.append(Instruction(Opcode.PUSH, [f"R{i}"]))

            program.extend(body)

            for i in reversed(used_regs):
                program.append(Instruction(Opcode.POP, [f"R{i}"]))

            program.append(Instruction(Opcode.IRET))
            program.append(f"{label_skip}:")
            return None

        # Объявление функции, просто добавляется процедуру в код программы и перед ним jmp на всякий

        if op == "defun":
            if len(node) != 4:
                raise SyntaxError(
                    "Контрукция defun требует: (defun имя (аргументы) тело)",
                )

            func_name = node[1]
            arg_list = node[2]
            body_expr = node[3]

            if not isinstance(arg_list, list):
                raise TypeError(
                    "Список аргументов функции должен быть списком в скобках ()",
                )

            arg_names = [name for name in arg_list if isinstance(name, str)]

            if not isinstance(func_name, str) or len(arg_names) != len(arg_list):
                raise TypeError(
                    f"Имя функции и её аргументы должны быть строками: {node[1]}",
                )
            if len(arg_names) != len(set(arg_names)):
                raise SyntaxError(
                    f"Косяк в функции {func_name}: аргументы имеют одинаковые имена",
                )

            label_after_func = make_label(f"skip_{func_name}")
            label_epilogue = make_label(f"ret_{func_name}")

            # Ставим JMP перед самой функции

            program.append(Instruction(Opcode.JMP, [label_after_func]))
            program.append(f"fn:{func_name}:")

            old_locals = local_vars.copy()
            old_reg = current_reg

            local_vars = {name: f"R{i + 1}" for i, name in enumerate(arg_names)}
            current_reg = len(arg_names) + 1

            result_reg = allocate_reg()
            compile_tail_body(body_expr, func_name, label_epilogue, result_reg)

            program.append(f"{label_epilogue}:")

            # При выходе результат функции помещаем в R1 и делаем RET

            if result_reg != "R1":
                program.append(Instruction(Opcode.ADD, ["R1", result_reg, "R0"]))

            program.append(Instruction(Opcode.RET))

            local_vars = old_locals
            current_reg = old_reg
            program.append(f"{label_after_func}:")
            return None

        # Печать через PMIO

        if op == "print":
            if len(node) != 2:
                raise SyntaxError(
                    "Команда print требует один аргумент: print значение",
                )
            val_reg = compile_value(node[1])
            program.append(Instruction(Opcode.OUT, [OUTPUT_PORT, val_reg]))
            return val_reg

        # Присваивание setq, то бишь создание переменной

        if op == "setq":
            if len(node) != 3:
                raise SyntaxError(
                    "Команда setq требует ровно 2 аргумента: setq имя значение",
                )

            var_name = node[1]
            value_expr = node[2]

            # Проверяем по всяким формальностям

            if not isinstance(var_name, str):
                raise TypeError(
                    f"Имя переменной должно быть строкой, получено: {var_name}",
                )

            if var_name in RESERVED_KEYWORDS:
                raise SyntaxError(
                    f"Нельзя использовать зарезервированное слово {var_name} в качестве имени переменной",
                )

            if var_name in local_vars:
                # Если это локальная переменная, то просто копируем значение

                val_reg = compile_value(value_expr)
                program.append(
                    Instruction(Opcode.ADD, [local_vars[var_name], val_reg, "R0"]),
                )
                return val_reg

            # Если глобальная переменная, то просто выделяем новый адрес и косвенно загружаем значение

            addr = get_or_allocate_var(var_name)
            val_reg = compile_value(value_expr)

            addr_reg = allocate_reg()
            program.append(Instruction(Opcode.LDI, [addr_reg, addr]))
            program.append(Instruction(Opcode.ST, [val_reg, addr_reg, 0]))
            free_reg()

            return val_reg

        # Ветвление if

        if op == "if":
            if len(node) != 4:
                raise SyntaxError(
                    "if требует ровно 3 аргумента: if условие then else",
                )

            condition = node[1]
            then_branch = node[2]
            else_branch = node[3]

            # Создаём на будущее метки

            label_else = make_label("else")
            label_end = make_label("end")

            jump_to_else_op = compile_condition(condition)
            result_reg = allocate_reg()

            # Если условие ложно, то делаем переход в ветку else

            program.append(Instruction(jump_to_else_op, [label_else]))

            # THEN
            then_reg = compile_expr(then_branch)
            if then_reg is not None:
                program.append(Instruction(Opcode.ADD, [result_reg, then_reg, "R0"]))
                free_reg()
            program.append(Instruction(Opcode.JMP, [label_end]))

            # ELSE
            program.append(f"{label_else}:")
            else_reg = compile_expr(else_branch)
            if else_reg is not None:
                program.append(Instruction(Opcode.ADD, [result_reg, else_reg, "R0"]))
                free_reg()

            # END
            program.append(f"{label_end}:")
            if then_reg is None or else_reg is None:
                free_reg()
                return None
            return result_reg

        # Вызов пользовательской функции, всё реализуется просто через сохранение регистров и обычной CALL

        if op in functions:
            passed_args = node[1:]
            except_args_count = functions[op]

            if len(passed_args) != except_args_count:
                raise TypeError(
                    f"Функция {op} ожидает {except_args_count},"
                    f"но было передано {len(passed_args)}",
                )

            active_regs = [f"R{i}" for i in range(1, current_reg)]
            arg_temp_regs = [compile_value(arg) for arg in passed_args]

            # Сохраняем старые регистры в стек

            for r in active_regs:
                program.append(Instruction(Opcode.PUSH, [r]))

            for i, temp_r in enumerate(arg_temp_regs):
                target_r = f"R{i + 1}"
                if temp_r != target_r:
                    program.append(Instruction(Opcode.ADD, [target_r, temp_r, "R0"]))

            program.append(Instruction(Opcode.CALL, [f"fn:{op}"]))

            for _ in arg_temp_regs:
                free_reg()

            res_reg = allocate_reg()
            program.append(Instruction(Opcode.ADD, [res_reg, "R1", "R0"]))

            for r in reversed(active_regs):
                program.append(Instruction(Opcode.POP, [r]))

            return res_reg

        # Вывод в порт

        if op == "out":
            if len(node) != 3:
                raise SyntaxError(
                    "Команда out требует два аргумента формата (out порт значение)",
                )

            port_num = node[1]
            val_expr = node[2]

            if not isinstance(port_num, int) or port_num != OUTPUT_PORT:
                raise ValueError(f"Для out доступен только порт {OUTPUT_PORT}")

            val_reg = compile_value(val_expr)
            program.append(Instruction(Opcode.OUT, [port_num, val_reg]))
            return val_reg

        # Ввод из порта

        if op == "in":
            if len(node) != 2:
                raise SyntaxError("Команда in требует 1 аргумент: in порт")

            port_num = node[1]
            if not isinstance(port_num, int) or port_num != INPUT_PORT:
                raise ValueError(f"Для in доступен только порт {INPUT_PORT}")

            reg = allocate_reg()
            program.append(Instruction(Opcode.IN, [reg, port_num]))
            return reg

        # Унарные операции

        if op == "not":
            if len(node) != 2:
                raise SyntaxError("Команда not  требует один аргумент")
            arg_reg = compile_value(node[1])
            program.append(Instruction(Opcode.NOT, [arg_reg, arg_reg]))
            return arg_reg

        if op == "inc":
            if len(node) != 2:
                raise SyntaxError("Команда inc требует один аргумент")
            arg_reg = compile_value(node[1])
            program.append(Instruction(Opcode.INC, [arg_reg]))
            return arg_reg

        if op == "dec":
            if len(node) != 2:
                raise SyntaxError("Команда dec требует один аргумент")
            arg_reg = compile_value(node[1])
            program.append(Instruction(Opcode.DEC, [arg_reg]))
            return arg_reg

        # Арифметика вариативная (+ 1 2 3...)

        # Сравнение вне условия, превращаем флаги в число 1 или 0. Нарпимер (= 2 3)

        if op in COMPARE_OPS:
            label_false = make_label("cmp_false")
            label_end = make_label("cmp_end")

            jump_if_false = compile_condition(node)
            result_reg = allocate_reg()

            program.append(Instruction(jump_if_false, [label_false]))

            # Если условие истино, что грузим единицу

            program.append(Instruction(Opcode.LDI, [result_reg, 1]))
            program.append(Instruction(Opcode.JMP, [label_end]))

            # Иначе ноль

            program.append(f"{label_false}:")
            program.append(Instruction(Opcode.LDI, [result_reg, 0]))

            program.append(f"{label_end}:")
            return result_reg

        # Если + и * принимают сразу несколько операндов

        if op in ("+", "*"):
            if len(node) < 3:
                raise SyntaxError(f"Операция {op} требует как минимум 2 операнда")

            accum_reg = compile_value(node[1])
            for next_expr in node[2:]:
                next_reg = compile_value(next_expr)
                if op == "+":
                    program.append(
                        Instruction(Opcode.ADD, [accum_reg, accum_reg, next_reg]),
                    )
                elif op == "*":
                    program.append(
                        Instruction(Opcode.MUL, [accum_reg, accum_reg, next_reg]),
                    )
                free_reg()

            return accum_reg

        # Бинарная арифметика и побитовые операции

        if op in BINARY_OPS:
            if len(node) != 3:
                raise SyntaxError(
                    f"Операция {op} требует ровно 2 операнда, а получили {len(node) - 1}",
                )

            left = node[1]
            right = node[2]

            left_reg = compile_value(left)
            right_reg = compile_value(right)

            if op == "-":
                program.append(Instruction(Opcode.SUB, [left_reg, left_reg, right_reg]))
            elif op == "/":
                program.append(Instruction(Opcode.DIV, [left_reg, left_reg, right_reg]))
            elif op == "%":
                program.append(Instruction(Opcode.MOD, [left_reg, left_reg, right_reg]))
            elif op == "and":
                program.append(Instruction(Opcode.AND, [left_reg, left_reg, right_reg]))
            elif op == "or":
                program.append(Instruction(Opcode.OR, [left_reg, left_reg, right_reg]))
            elif op == "xor":
                program.append(Instruction(Opcode.XOR, [left_reg, left_reg, right_reg]))
            elif op in ("lsl", "<<"):
                program.append(Instruction(Opcode.LSL, [left_reg, left_reg, right_reg]))
            elif op in ("lsr", ">>"):
                program.append(Instruction(Opcode.LSR, [left_reg, left_reg, right_reg]))

            free_reg()
            return left_reg

        raise SyntaxError(f"Неизвестная операция или необъявленная функция: '{op}'")
    return None


# Вывод адреса, машинного слова в 16-ричке, название команды с аргументами и исходное Lisp выражение из source


def generate_listing(instructions: list[Instruction]) -> str:
    lines = []
    for index, instr in enumerate(instructions):
        addr = index * WORD_SIZE
        if isinstance(instr, Instruction):
            hex_code = f"0x{instr.encode():08X}"
            source = f"  ; {instr.source}" if instr.source else ""
            lines.append(f"{addr:04d} - {hex_code} - {instr}{source}")
        elif isinstance(instr, int):
            hex_code = f"0x{instr:08X}"
            lines.append(f"{addr:04d} - {hex_code} - raw_word 0x{instr:04X}")
    return "\n".join(lines)


# Компиляция исполняемого бинарного файла


def compile_file(
    source_file: str,
    target_file: str,
    listing_file: str | None = None,
) -> None:

    global program, symbol_table, data_memory, functions, local_vars
    global current_reg, label_counter, data_address_counter, interrupt_handler

    program = []  # Инструкции и символические метки, которые генерит компилятор
    symbol_table = {}  # Имена глобальных переменных и выделенные им адреса
    data_memory = {}  # Значения, которые нужно положить в область данных бинарного образа
    functions = {}  # Имена функций и число их аргументов
    local_vars = {}  # Параметры текущей функции с регистрами
    current_reg = 1  # Текущий выбранный регистр
    label_counter = 0  # Номер уникальной метки
    data_address_counter = DATA_SEGMENT_START
    interrupt_handler = None

    code_text = Path(source_file).read_text(encoding="utf-8")

    # Проводим парсинг данных их файлика

    tokens = tokenize(code_text)
    ast = parse(tokens)
    if tokens:
        raise SyntaxError("После первого выражения остались лишние токены")

    # Первая проходка для определения функций и их аргументов

    collect_function_signatures(ast)

    # Главный цикл прохода, где происходит генерация набора инструкций и тд и тп

    compile_expr(ast)

    # Компонуем программу, добавляя векторы прерывания, вычисляем адреса меток и подставляем их в инструкции и добавляем в конце HLT
    # Проверяем, что у нас есть обработчик прерываний.

    machine_code = link_program(program)
    if interrupt_handler is None and any(i.opcode == Opcode.EI for i in machine_code):
        raise SyntaxError("Для EI нужен обработчик definterrupt")

    # Проверяем, что код помещается до адреса 4000

    if len(machine_code) * WORD_SIZE > DATA_SEGMENT_START:
        raise RuntimeError(
            f"Код занял {len(machine_code) * WORD_SIZE} байт и залезает "
            f"в сегмент данных (адрес {DATA_SEGMENT_START}) бяка бяка",
        )

    # Проверяем, что данные не залазают на стек

    if data_address_counter > STACK_LIMIT:
        raise RuntimeError(
            f"Данные заняли память до адреса {data_address_counter} "
            f"и залезают в область стека (адрес {STACK_LIMIT})",
        )

    # Создаём бинарный образ памяти.

    memory_dump = [0] * 4096

    for addr, instr in enumerate(machine_code):
        if isinstance(instr, Instruction):
            memory_dump[addr] = instr.encode()
        elif isinstance(instr, int):
            memory_dump[addr] = instr

    # Данные из дата мемори кладём по их байтовым адресам, делённым на четырку, дабы закинуть это в массив питончика. Пишем в биг эндиан.

    for addr, val in data_memory.items():
        memory_dump[addr // WORD_SIZE] = val

    with Path(target_file).open("wb") as f:
        f.writelines(struct.pack(">I", word & 0xFFFF_FFFF) for word in memory_dump)

    print(f"Машинный код записан в: {target_file}")

    if listing_file:
        listing_text = generate_listing(machine_code)
        Path(listing_file).write_text(listing_text, encoding="utf-8")
        print(f"Отладочный листинг записан в: {listing_file}")


# Точка входа в программу


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Консольный транслятор LISP в машинный код RISC проца",
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Путь к исходному файлу .lisp",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Путь к выходному бинарному файлу .bin",
    )
    parser.add_argument(
        "-l",
        "--listing",
        default=None,
        help="Путь к файлу листинга .txt, опционально",
    )

    args = parser.parse_args()

    try:
        compile_file(args.input, args.output, args.listing)
    except Exception as e:
        print(f"Ошибка компиляции: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
