from isa import Opcode, Instruction

# Класс, отвечающий за физические компоненты процессора - память, регистровый файл, АЛУ, Флаги и Порты ввода-вывода

class DataPath:

    # Что у нас будет инициализировать в общем-то

    def __init__(self, memory_size: int = 4096):

        # В начале расположим инструкции, опосля строки и переменные и с конца будет расти у нас великий и ужасный стек

        self.memory = [0] * memory_size             # RAM

        self.registers = [0] * 16                   # REG (R0 - R15)

        self.status_register = 0                    # Регистр состояния процессора

        self.saved_status_register = 0              # Регистр для сохранения флагов при уходе в прерывание

        self.port_0_in = []                         # Буфер входных символов
        self.port_1_out = []                        # Буфер вывода на экран

        self.registers[12] = memory_size - 1        # SP


    # Флажки

    @property                                       # N
    def flag_n(self) -> int:
        return (self.status_register >> 3) & 1

    @flag_n.setter
    def flag_n(self, val: int):
        if val: self.status_register |= (1 << 3)
        else: self.status_register &= ~(1 << 3)


    @property                                       # Z
    def flag_z(self) -> int:
        return (self.status_register >> 2) & 1

    @flag_z.setter
    def flag_z(self, val: int):
        if val: self.status_register |= (1 << 2)
        else: self.status_register &= ~(1 << 2)

    
    @property                                       # C
    def flag_c(self) -> int:
        return (self.status_register >> 1) & 1

    @flag_c.setter
    def flag_c(self, val: int):
        if val: self.status_register |= (1 << 1)
        else: self.status_register &= ~(1 << 1)

    
    @property                                       # V
    def flag_v(self) -> int:
        return (self.status_register) & 1

    @flag_v.setter
    def flag_v(self, val: int):
        if val: self.status_register |= (1 << 0)
        else: self.status_register &= ~(1 << 0)

    # Регистровые файлы

    def get_reg_idx(self, reg_name: str) -> int:    # Преврщает имя регистра в нужный нам индекс
        if reg_name == "SP": return 12
        if reg_name == "LR": return 13
        if reg_name == "IRA": return 14
        if reg_name == "PC": return 15
        return int(reg_name.replace("R", ""))

    def read_reg(self, reg_name: str) -> int:       # Возвращает 32-битное значение их регистра
        idx = self.get_reg_idx(reg_name)
        return self.registers[idx]

    def write_reg(self, reg_name: str, value: int): # Записывает 32-битное значение в регистр
        idx = self.get_reg_idx(reg_name)

        # В R0 нельзя ничего записать

        if idx == 0:
            return

        self.registers[idx] = value & 0xFFFF_FFFF

    # АЛУ

    def execute_alu(self, op: Opcode, src1: int, src2: int = 0) -> int:

        res = 0

        # Арифметика

        if op == Opcode.ADD:
            res = src1 + src2
        elif op in (Opcode.SUB, Opcode.CMP):
            res = src2 - src2
        elif op == Opcode.MUL:
            res = src1 * src2
        elif op == Opcode.DIV:
            res = src1 // src2 if src2 != 0 else 0
        elif op == Opcode.MOD:
            res = src1 % src2 if src2 != 0 else 0

        