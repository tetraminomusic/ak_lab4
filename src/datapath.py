from isa import WORD_SIZE, Opcode

STACK_LIMIT = 12400


def to_signed(value: int) -> int:
    value &= 0xFFFF_FFFF
    return value - (1 << 32) if value & (1 << 31) else value


def signed_div(src1: int, src2: int) -> int:
    if to_signed(src2) == 0:
        return 0

    left = to_signed(src1)
    right = to_signed(src2)

    quotient = abs(left) // abs(right)
    return -quotient if (left < 0) != (right < 0) else quotient


def signed_mod(src1: int, src2: int) -> int:
    if to_signed(src2) == 0:
        return 0

    return to_signed(src1) - to_signed(src2) * signed_div(src1, src2)


# Класс, отвечающий за физические компоненты процессора - память, регистровый файл, АЛУ, Флаги и Порты ввода-вывода


class DataPath:
    # Что у нас будет инициализировать в общем-то

    def __init__(self, memory_size: int = 4096) -> None:

        # В начале расположим инструкции, опосля строки и переменные и с конца будет расти у нас великий и ужасный стек

        self.memory = [0] * memory_size  # RAM

        # Чистый регистровый файл

        self.registers = [0] * 16  # REG

        # Служебные регистры

        self.pc = 0  # Счётчик команд
        self.sp = (memory_size - 1) * WORD_SIZE  # Вершина стека
        self.cr = 0  # Регистр команд
        self.status_register = 0  # Регистр состояния процессора

        # Ввод-вывод

        self.in_reg = 0
        self.out_reg = 0
        self.port_1_out: list[int] = []  # Буфер вывода на экран

        # Сигнал о запросе прерывания от ВУ

        self.dev_signal = 0

        self.flag_ie = 0  # Прерывания запрещены до команды EI

    # Регистр состояния

    @property  # C
    def flag_c(self) -> int:
        return (self.status_register >> 0) & 1

    @flag_c.setter
    def flag_c(self, val: int) -> None:
        if val:
            self.status_register |= 1 << 0
        else:
            self.status_register &= ~(1 << 0)

    @property  # V
    def flag_v(self) -> int:
        return (self.status_register >> 1) & 1

    @flag_v.setter
    def flag_v(self, val: int) -> None:
        if val:
            self.status_register |= 1 << 1
        else:
            self.status_register &= ~(1 << 1)

    @property  # Z
    def flag_z(self) -> int:
        return (self.status_register >> 2) & 1

    @flag_z.setter
    def flag_z(self, val: int) -> None:
        if val:
            self.status_register |= 1 << 2
        else:
            self.status_register &= ~(1 << 2)

    @property  # N
    def flag_n(self) -> int:
        return (self.status_register >> 3) & 1

    @flag_n.setter
    def flag_n(self, val: int) -> None:
        if val:
            self.status_register |= 1 << 3
        else:
            self.status_register &= ~(1 << 3)

            # 0 - резерв

    @property  # IE - запрет/разрешения прерывания
    def flag_ie(self) -> int:
        return (self.status_register >> 5) & 1

    @flag_ie.setter
    def flag_ie(self, val: int) -> None:
        if val:
            self.status_register |= 1 << 5
        else:
            self.status_register &= ~(1 << 5)

    @property  # IRQ
    def irq(self) -> int:
        return 1 if (self.dev_signal and self.flag_ie) else 0

    # Регистровые файлы

    def get_reg_idx(
        self,
        reg_name: str,
    ) -> int:  # Превращает имя регистра в индекс 0..15
        return int(reg_name.replace("R", ""))

    def read_reg(
        self,
        reg_name: str,
    ) -> int:  # Возвращает 32-битное значение из регистра
        idx = self.get_reg_idx(reg_name)
        return self.registers[idx]

    def write_reg(
        self,
        reg_name: str,
        value: int,
    ) -> None:  # Записывает 32-битное значение в регистр
        idx = self.get_reg_idx(reg_name)

        # В R0 нельзя ничего записать
        if idx == 0:
            return

        self.registers[idx] = value & 0xFFFF_FFFF

    def effective_address(self, base_reg: str, offset: int) -> int:
        # Сложение для шины адреса проходит при отключённой записи NZVC.
        return self.read_reg(base_reg) + offset

    def signal_port_in(self, destination: str) -> None:
        self.write_reg(destination, self.in_reg)
        self.dev_signal = 0

    def signal_port_out(self, source: str) -> int:
        self.out_reg = self.read_reg(source)
        self.port_1_out.append(self.out_reg)
        return self.out_reg

    # АЛУ

    def execute_alu(self, op: Opcode, src1: int, src2: int = 0) -> int:

        res = 0

        # Арифметика

        if op == Opcode.ADD:
            res = src1 + src2
        elif op in (Opcode.SUB, Opcode.CMP):
            res = src1 - src2
        elif op == Opcode.MUL:
            res = src1 * src2
        elif op == Opcode.DIV:
            res = signed_div(src1, src2)
        elif op == Opcode.MOD:
            res = signed_mod(src1, src2)
        elif op == Opcode.INC:
            res = src1 + 1
        elif op == Opcode.DEC:
            res = src1 - 1

        # Логические операции

        elif op == Opcode.AND:
            res = src1 & src2
        elif op == Opcode.OR:
            res = src1 | src2
        elif op == Opcode.XOR:
            res = src1 ^ src2
        elif op == Opcode.NOT:
            res = ~src1

        # Сдвиги

        elif op == Opcode.LSL:
            res = (src1 << (src2 & 31)) & 0xFFFF_FFFF
        elif op == Opcode.LSR:
            res = (src1 & 0xFFFF_FFFF) >> (src2 & 31)

        # NZVC

        self.flag_n = 1 if (res & (1 << 31)) != 0 else 0  # N
        self.flag_z = 1 if (res & 0xFFFF_FFFF) == 0 else 0  # Z
        self.flag_c = 1 if (res > 0xFFFF_FFFF) else 0  # C

        if op in (Opcode.ADD, Opcode.INC):  # V
            self.flag_v = 1 if (~(src1 ^ src2) & (src1 ^ res) & 0x80000000) != 0 else 0

        elif op in (Opcode.SUB, Opcode.CMP, Opcode.DEC):
            self.flag_v = 1 if ((src1 ^ src2) & (src1 ^ res) & 0x80000000) != 0 else 0

        else:
            self.flag_v = 0

        return res & 0xFFFF_FFFF
