import logging

from cache import Cache
from datapath import STACK_LIMIT, DataPath
from isa import WORD_SIZE, Opcode

T0_FETCH = 0
T1_DECODE = 1
T2_EXECUTE = 2
T3_MEMORY = 3
T4_INTERRUPT = 4

STEP_NAMES = {
    T0_FETCH: "T0 FETCH",
    T1_DECODE: "T1 DECODE",
    T2_EXECUTE: "T2 EXEC",
    T3_MEMORY: "T3 MEM/WB",
    T4_INTERRUPT: "T4 INT",
}

ALU_BINARY_OPS = (
    Opcode.ADD,
    Opcode.SUB,
    Opcode.MUL,
    Opcode.DIV,
    Opcode.MOD,
    Opcode.AND,
    Opcode.OR,
    Opcode.XOR,
    Opcode.LSL,
    Opcode.LSR,
)

BRANCH_OPS = (Opcode.JMP, Opcode.JZ, Opcode.JNZ, Opcode.JL, Opcode.JGE)

# Устройство управления типа Hardwired


class ControlUnit:
    def __init__(
        self,
        data_path: DataPath,
        schedule: list[tuple[int, str | int]] | None = None,
        sources: dict[int, str] | None = None,
        *,
        cache_enabled: bool = True,
    ) -> None:
        self.dp = data_path
        self.cache = Cache(self.dp.memory, enabled=cache_enabled)
        self.current_tick = 0  # Счётчик прошедших тактов
        self.instruction_counter = 0  # Сколько инструкций выполнили
        self.is_halted = False  # Флаг остановки для команды HLT

        self.step = T0_FETCH

        self.op: Opcode | None = None
        self.rd_idx = 0
        self.rs1_idx = 0
        self.rs2_idx = 0
        self.imm = 0

        self.mem_op = ""
        self.mem_addr = 0
        self.mem_value = 0
        self.next_pc = 0
        self.current_addr = 0  # Адрес команды, которая сейчас в регистре команд

        self.stall_ticks = 0

        self.int_active = False

        self.step_label = STEP_NAMES[T0_FETCH]

        # Расписание прерываний

        self.schedule = schedule if schedule is not None else []
        self.sources = sources if sources is not None else {}

        self.check_interrupt_schedule()

    def check_interrupt_schedule(self) -> None:
        while self.schedule and self.current_tick >= self.schedule[0][0]:
            _, char = self.schedule.pop(0)
            ascii_code = ord(char) if isinstance(char, str) else int(char)

            if self.dp.dev_signal:
                logging.warning(
                    "[ТАКТ %d] ВУ затёрло непрочитанный байт в порту 0!",
                    self.current_tick,
                )

            self.dp.in_reg = ascii_code
            self.dp.dev_signal = 1

            char_repr = (
                chr(ascii_code) if 32 <= ascii_code <= 126 else f"\\x{ascii_code:02x}"
            )
            logging.info(
                "[ТАКТ %d] ВУ прислало символ '%s' (ASCII %d), провод IntRq = 1!",
                self.current_tick,
                char_repr,
                ascii_code,
            )

    def tick(self) -> None:  # Один такт тактового генератора
        if self.is_halted or not self.dp.flag_p:
            self.is_halted = True
            return

        self.current_tick += 1

        self.check_interrupt_schedule()

        if self.stall_ticks > 0:
            self.stall_ticks -= 1
            self.step_label = "STALL"
            return

        self.step_label = STEP_NAMES[self.step]

        if self.step == T0_FETCH:
            self.instruction_fetch()
        elif self.step == T1_DECODE:
            self.instruction_decode()
        elif self.step == T2_EXECUTE:
            self.execute()
        elif self.step == T3_MEMORY:
            self.memory_access()
        elif self.step == T4_INTERRUPT:
            self.interrupt_fetch()

    def __repr__(self) -> str:
        """Возвращает строку с текущими значениями для табличного вывода."""
        nzcv = f"{self.dp.status_register & 0xF:04b}"

        word = self.dp.cr
        op_code = (word >> 24) & 0xFF
        try:
            op_name = Opcode(op_code).name
            rd = (word >> 20) & 0xF
            rs1 = (word >> 16) & 0xF
            imm = word & 0xFFFF
            instr_str = f"{op_name} R{rd}, R{rs1}, {imm}"
        except ValueError:
            instr_str = "DATA"
        hex_str = f"{word:08X}"

        registers = " ".join(f"{value:>5}" for value in self.dp.registers)

        source = self.sources.get(self.current_addr, "")
        if len(source) > 34:
            source = source[:33] + "…"

        return (
            f"| {self.current_tick:^6} "
            f"| {self.step_label:<9} "
            f"| {self.dp.pc:^5} "
            f"| {hex_str:^8} "
            f"| {instr_str:<22} "
            f"| {self.dp.sp:^6} "
            f"| {nzcv:^6} "
            f"| {self.cache.last_status:^9} "
            f"| {'INT' if self.int_active else '-':^4} "
            f"| {registers} "
            f"| {source}"
        )

    def instruction_fetch(self) -> None:
        if not self.check_address(self.dp.pc):
            return

        self.current_addr = self.dp.pc
        raw_word, wait_ticks = self.cache.read(self.dp.pc)

        self.stall_ticks = wait_ticks - 1
        self.dp.cr = raw_word
        self.next_pc = self.dp.pc + WORD_SIZE
        self.step = T1_DECODE

    def instruction_decode(self) -> None:
        word = self.dp.cr
        op_val = (word >> 24) & 0xFF

        if op_val in (0, Opcode.HLT):
            self.is_halted = True
            self.dp.flag_p = 0
            return

        try:
            self.op = Opcode(op_val)
        except ValueError:
            logging.warning(
                "[ТАКТ %d] Неизвестный код операции 0x%02X, останов",
                self.current_tick,
                op_val,
            )
            self.is_halted = True
            self.dp.flag_p = 0
            return

        self.rd_idx = (word >> 20) & 0xF
        self.rs1_idx = (word >> 16) & 0xF
        self.rs2_idx = (word >> 12) & 0xF
        self.imm = word & 0xFFFF

        self.mem_op = ""
        self.step = T2_EXECUTE

    def execute(self) -> None:
        op = self.op
        rd = f"R{self.rd_idx}"
        rs1 = f"R{self.rs1_idx}"
        rs2 = f"R{self.rs2_idx}"

        if op == Opcode.LDI:
            self.dp.write_reg(rd, self.imm)
            self.finish_instruction()

        elif op == Opcode.LD:
            self.mem_addr = self.dp.read_reg(rs1) + self.imm
            self.mem_op = "read"
            self.step = T3_MEMORY

        elif op == Opcode.ST:
            self.mem_addr = self.dp.read_reg(rs1) + self.imm
            self.mem_value = self.dp.read_reg(rd)
            self.mem_op = "write"
            self.step = T3_MEMORY

        elif op in ALU_BINARY_OPS:
            result = self.dp.execute_alu(
                op,
                self.dp.read_reg(rs1),
                self.dp.read_reg(rs2),
            )
            self.dp.write_reg(rd, result)
            self.finish_instruction()

        elif op == Opcode.CMP:
            self.dp.execute_alu(op, self.dp.read_reg(rd), self.dp.read_reg(rs1))
            self.finish_instruction()

        elif op in (Opcode.INC, Opcode.DEC):
            result = self.dp.execute_alu(op, self.dp.read_reg(rd))
            self.dp.write_reg(rd, result)
            self.finish_instruction()

        elif op == Opcode.NOT:
            result = self.dp.execute_alu(op, self.dp.read_reg(rs1))
            self.dp.write_reg(rd, result)
            self.finish_instruction()

        elif op in BRANCH_OPS:
            if self.branch_taken(op):
                self.next_pc = self.imm
            self.finish_instruction()

        elif op == Opcode.CALL:
            self.mem_addr = self.dp.sp
            self.mem_value = self.next_pc
            self.mem_op = "write"
            self.dp.sp -= WORD_SIZE
            self.next_pc = self.imm
            self.check_stack()
            self.step = T3_MEMORY

        elif op == Opcode.RET:
            if not self.check_stack_bottom():
                return
            self.dp.sp += WORD_SIZE
            self.mem_addr = self.dp.sp
            self.mem_op = "read"
            self.step = T3_MEMORY

        elif op == Opcode.PUSH:
            self.mem_addr = self.dp.sp
            self.mem_value = self.dp.read_reg(rd)
            self.mem_op = "write"
            self.dp.sp -= WORD_SIZE
            self.check_stack()
            self.step = T3_MEMORY

        elif op == Opcode.POP:
            if not self.check_stack_bottom():
                return
            self.dp.sp += WORD_SIZE
            self.mem_addr = self.dp.sp
            self.mem_op = "read"
            self.step = T3_MEMORY

        elif op == Opcode.IRET:
            self.mem_op = "read"
            self.step = T3_MEMORY

        elif op == Opcode.OUT:
            port = self.imm
            self.dp.out_reg = self.dp.read_reg(rd)
            if port == 1:
                self.dp.port_1_out.append(self.dp.out_reg)

                value = self.dp.out_reg
                shown = chr(value) if 32 <= value <= 126 else f"\\x{value:02x}"
                logging.info(
                    "[ТАКТ %d] Процессор вывел в порт 1 символ '%s' (код %d)",
                    self.current_tick,
                    shown,
                    value,
                )
            self.finish_instruction()

        elif op == Opcode.IN:
            self.dp.write_reg(rd, self.dp.in_reg)

            self.dp.dev_signal = 0
            self.finish_instruction()

        elif op == Opcode.EI:
            self.dp.flag_ie = 1
            self.finish_instruction()

        elif op == Opcode.DI:
            self.dp.flag_ie = 0
            self.finish_instruction()

        else:
            self.finish_instruction()

    def check_stack(self) -> None:
        if self.dp.sp >= STACK_LIMIT:
            return

        logging.error(
            "[ТАКТ %d] Переполнение стека: SP = %d залез в сегмент данных",
            self.current_tick,
            self.dp.sp,
        )
        self.is_halted = True
        self.dp.flag_p = 0

    def check_address(self, addr: int) -> bool:
        if 0 <= addr < len(self.dp.memory) * WORD_SIZE:
            return True

        logging.error(
            "[ТАКТ %d] Обращение по адресу %d за пределами памяти",
            self.current_tick,
            addr,
        )
        self.is_halted = True
        self.dp.flag_p = 0
        return False

    def check_stack_bottom(self) -> bool:
        if self.dp.sp < (len(self.dp.memory) - 1) * WORD_SIZE:
            return True

        logging.error(
            "[ТАКТ %d] Стек пуст, снимать с него нечего",
            self.current_tick,
        )
        self.is_halted = True
        self.dp.flag_p = 0
        return False

    def branch_taken(self, op: Opcode) -> bool:
        if op == Opcode.JMP:
            return True
        if op == Opcode.JZ:
            return self.dp.flag_z == 1
        if op == Opcode.JNZ:
            return self.dp.flag_z == 0
        if op == Opcode.JL:
            return self.dp.flag_n != self.dp.flag_v
        if op == Opcode.JGE:
            return self.dp.flag_n == self.dp.flag_v
        return False

    def memory_access(self) -> None:
        op = self.op
        rd = f"R{self.rd_idx}"

        if op == Opcode.IRET:
            if not self.check_stack_bottom():
                return
            self.dp.sp += WORD_SIZE
            ps_value, wait_ps = self.cache.read(self.dp.sp)
            self.dp.sp += WORD_SIZE
            pc_value, wait_pc = self.cache.read(self.dp.sp)
            self.stall_ticks = wait_ps + wait_pc - 1

            self.dp.status_register = ps_value
            self.next_pc = pc_value
            self.dp.flag_ie = 1
            self.int_active = False

            logging.info("[ТАКТ %d] Выход из прерывания (IRET)", self.current_tick)
            self.finish_instruction()
            return

        if not self.check_address(self.mem_addr):
            return

        if self.mem_op == "write":
            self.stall_ticks = self.cache.write(self.mem_addr, self.mem_value) - 1
            self.finish_instruction()
            return

        value, wait_ticks = self.cache.read(self.mem_addr)
        self.stall_ticks = wait_ticks - 1

        if op in (Opcode.LD, Opcode.POP):
            self.dp.write_reg(rd, value)
        elif op == Opcode.RET:
            self.next_pc = value

        self.finish_instruction()

    def finish_instruction(self) -> None:
        self.instruction_counter += 1
        self.dp.pc = self.next_pc

        self.step = T4_INTERRUPT if self.dp.irq else T0_FETCH

    def interrupt_fetch(self, vector_address: int = WORD_SIZE) -> None:
        wait_pc = self.cache.write(self.dp.sp, self.dp.pc)
        self.dp.sp -= WORD_SIZE
        wait_ps = self.cache.write(self.dp.sp, self.dp.status_register)
        self.dp.sp -= WORD_SIZE
        self.stall_ticks = wait_pc + wait_ps - 1
        self.check_stack()

        self.dp.flag_ie = 0
        self.int_active = True
        self.dp.pc = vector_address
        self.step = T0_FETCH

        logging.info(
            "[ТАКТ %d] Вход в прерывание: PC и PS сохранены в стек",
            self.current_tick,
        )
