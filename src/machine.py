from isa import Opcode, Instruction

# Класс, отвечающий за физические компоненты процессора - память, регистровый файл, АЛУ, Флаги и Порты ввода-вывода

class DataPath:

    # Что у нас будет инициализировать в общем-то

    def __init__(self, memory_size: int = 4096):

        # В начале расположим инструкции, опосля строки и переменные и с конца будет расти у нас великий и ужасный стек

        self.memory = [0] * memory_size                         # RAM

        self.registers = [0] * 16                               # REG (R0 - R15)

        self.status_register = 0                                # Регистр состояния процессора

        self.port_0_in = []                                     # Буфер входных символов
        self.port_1_out = []                                    # Буфер вывода на экран

        self.registers[12] = memory_size - 1                    # SP

        self.dev_signal = 0                                     # Сигнал о запросе прывания от ВУ

        self.flag_w = 1                                         # Процессор находится в непрерывном режиме
        self.flag_p = 1                                         # Процессора работает
        self.flag_ie = 1                                        # Прерывания по дефолту разрешены


    # Регистр состояния

    @property                                                   # C
    def flag_c(self) -> int:
        return (self.status_register >> 0) & 1

    @flag_c.setter
    def flag_c(self, val: int):
        if val: self.status_register |= (1 << 0)
        else: self.status_register &= ~(1 << 0)


    @property                                                   # V
    def flag_v(self) -> int:
        return (self.status_register >> 1) & 1

    @flag_v.setter
    def flag_v(self, val: int):
        if val: self.status_register |= (1 << 1)
        else: self.status_register &= ~(1 << 1)


    @property                                                   # Z
    def flag_z(self) -> int:
        return (self.status_register >> 2) & 1

    @flag_z.setter
    def flag_z(self, val: int):
        if val: self.status_register |= (1 << 2)
        else: self.status_register &= ~(1 << 2)


    @property                                                   # N
    def flag_n(self) -> int:
        return (self.status_register >> 3) & 1

    @flag_n.setter
    def flag_n(self, val: int):
        if val: self.status_register |= (1 << 3)
        else: self.status_register &= ~(1 << 3)


                                                                # 0 - резерв


    @property                                                   # IE - запрет/разрешения прерывания
    def flag_ie(self) -> int:
        return (self.status_register >> 5) & 1

    @flag_ie.setter
    def flag_ie(self, val: int): 
        if val: self.status_register |= (1 << 5)
        else:   self.status_register &= ~(1 << 5)

    @property                                                   # IRQ
    def irq(self) -> int:
       return 1 if (self.dev_signal and self.flag_ie) else 0    
    

    @property                                                   # W (1 - непрерывный режим, 0 - потактовый режим)
    def flag_w(self) -> int:
        return (self.status_register >> 7) & 1

    @flag_w.setter
    def flag_w(self, val: int):
        if val: self.status_register |= (1 << 7)
        else:   self.status_register &= ~(1 << 7)


    @property                                                   # P (Работа/Останов)                    
    def flag_p(self) -> int:
        return (self.status_register >> 8) & 1

    @flag_p.setter
    def flag_p(self, val: int):
        if val: self.status_register |= (1 << 8)
        else:   self.status_register &= ~(1 << 8)


    # Регистровые файлы

    def get_reg_idx(self, reg_name: str) -> int:                # Преврщает имя регистра в нужный нам индекс
        if reg_name in ("PS", "SR"): return 11
        if reg_name == "SP": return 12
        if reg_name == "LR": return 13
        if reg_name == "IRA": return 14
        if reg_name == "PC": return 15
        return int(reg_name.replace("R", ""))

    def read_reg(self, reg_name: str) -> int:                   # Возвращает 32-битное значение их регистра
        idx = self.get_reg_idx(reg_name)
        return self.registers[idx]

    def write_reg(self, reg_name: str, value: int):             # Записывает 32-битное значение в регистр
        idx = self.get_reg_idx(reg_name)

        # В R0 нельзя ничего записать

        if idx == 0:
            return

        self.registers[idx] = value & 0xFFFF_FFFF


    @property                                                   # Регистр состояния (Поменял, так как раньше предполагал, что PS будет все регистрового файла)
    def status_register(self) -> int:
        return self.registers[11]

    @status_register.setter
    def status_register(self, val: int):
        self.registers[11] = val & 0xFFFF_FFFF

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
            res = src1 // src2 if src2 != 0 else 0
        elif op == Opcode.MOD:
            res = src1 % src2 if src2 != 0 else 0
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
        elif op == Opcode.ASL:
            res = (src1 << (src2 & 31)) & 0xFFFF_FFFF
        elif op == Opcode.ASR:
            signed_src = src1 if src1 < 0x8000_0000 else src1 - 0x1_0000_0000
            res = (signed_src >> (src2 & 31)) & 0xFFFF_FFFF
        elif op == Opcode.ROL:
            shift = src2 & 31
            res = ((src1 << shift) | ((src1 & 0xFFFFFFFF) >> (32 - shift))) & 0xFFFFFFFF
        elif op == Opcode.ROR:
            shift = src2 & 31
            res = (((src1 & 0xFFFF_FFFF) >> shift) | (src1 << (32 - shift))) & 0xFFFF_FFFF

        # NZVC

        self.flag_n = 1 if (res & (1 << 31)) != 0 else 0        # N

        self.flag_z = 1 if (res & 0xFFFF_FFFF) == 0 else 0      # Z

        self.flag_c = 1 if (res > 0xFFFF_FFFF) else 0           # C

        if op == Opcode.ADD:                                    # V
            self.flag_v = 1 if (~(src1 ^ src2) & (src1 ^ res) & 0x80000000) != 0 else 0
        elif op in (Opcode.SUB, Opcode.CMP):
            self.flag_v = 1 if ((src1 ^ src2) & (src1 ^ res) & 0x80000000) != 0 else 0
        else:
            self.flag_v = 0

        return res & 0xFFFF_FFFF

# Устройство управления типа Hardwired

class ControlUnit:

    def __init__(self, data_path: DataPath):
        self.dp = data_path
        self.current_tick = 0                                   # Счётчик прошедших тактов
        self.instruction_counter = 0                            # Сколько инструкций выполнили
        self.is_halted = False                                  # Флаг остановки для команды HLT

    def tick(self):                                             # Один такт тактового генератора
        self.current_tick += 1

    def step(self):                                             # Выполнение одной инструкции от корки до корки
        if self.is_halted:
            return

        # Instruction Fetch

        pc = self.dp.read_reg("PC")                             # Узнаём текущий адрес
        instr = self.dp.memory[pc]                              # Достаём команду из памяти
        self.tick()                                             # На выборку уходит один такт

        # Если дошли до пустой ячейки/команда HLT - останавливаемся
        if instr == 0 or instr is None or (isinstance(instr, Instruction) and instr.opcode == Opcode.HLT):
            self.is_halted = True
            return

        # Decode

        # Execute. На данный момент мы получаем две переменные - класс команды + аргументы команды.
        
        op = instr.opcode
        args = instr.args
        next_pc = pc + 1

        # Работа с памятью и константами

        if op == Opcode.LDI:
            target_reg = args[0]
            number = args[1]
            self.dp.write_reg(target_reg, number)
            self.tick()

        elif op == Opcode.ST:
            val = self.dp.read_reg(args[0])
            base_addr = self.dp.read_reg(args[1])
            offset = args[2]
            self.dp.memory[base_addr + offset] = val
            self.tick()

        elif op == Opcode.LD:
            base_addr = self.dp.read_reg(args[1])
            offset = args[2]
            val = self.dp.memory[base_addr + offset]
            self.dp.write_reg(args[0], val)
            self.tick()

        # Арифметика

        elif op in (Opcode.ADD, Opcode.SUB, Opcode.MUL, Opcode.DIV, Opcode.MOD,
              Opcode.AND, Opcode.OR, Opcode.XOR, Opcode.LSL, Opcode.LSR,
              Opcode.ASL, Opcode.ASR, Opcode.ROL, Opcode.ROR, Opcode.CMP):

            if op == Opcode.CMP:
                v1 = self.dp.read_reg(args[0])
                v2 = self.dp.read_reg(args[1])
                self.dp.execute_alu(op, v1, v2)
            else:
                v1 = self.dp.read_reg(args[1])
                v2 = self.dp.read_reg(args[2])
                result = self.dp.execute_alu(op, v1, v2)
                self.dp.write_reg(args[0], result)

            self.tick()

        elif op in (Opcode.INC, Opcode.DEC):
            val = self.dp.read_reg(args[0])
            res = self.dp.execute_alu(op, val)
            self.dp.write_reg(args[0], res)
            self.tick()

        elif op == Opcode.NOT:
            val = self.dp.read_reg(args[1])
            res = self.dp.execute_alu(op, val)
            self.dp.write_reg(args[0], res)
            self.tick()

        # Ветвления

        elif op == Opcode.JMP:
            next_pc = args[0]
            self.tick()

        elif op == Opcode.JZ and self.dp.flag_z == 1:
            next_pc = args[0]
            self.tick()

        elif op == Opcode.JNZ and self.dp.flag_z == 0:
            next_pc = args[0]
            self.tick()

        elif op == Opcode.JL and (self.dp.flag_n != self.dp.flag_v):
            next_pc = args[0]
            self.tick()

        elif op == Opcode.JGE and (self.dp.flag_n == self.dp.flag_v):
            next_pc = args[0]
            self.tick()

        elif op == Opcode.JN and self.dp.flag_n == 1:
            next_pc = args[0]
            self.tick()

        elif op == Opcode.JNN and self.dp.flag_n == 0:
            next_pc = args[0]
            self.tick()

        elif op == Opcode.JC and self.dp.flag_c == 1:
            next_pc = args[0]
            self.tick()

        elif op == Opcode.JNC and self.dp.flag_c == 0:
            next_pc = args[0]
            self.tick()

        elif op == Opcode.JV and self.dp.flag_v == 1:
            next_pc = args[0]
            self.tick()

        elif op == Opcode.JNV and self.dp.flag_v == 0:
            next_pc = args[0]
            self.tick()



        # Функции + Стек

        elif op == Opcode.CALL:
            sp = self.dp.read_reg("SP")
            self.dp.memory[sp] = next_pc
            self.dp.write_reg("SP", sp - 1)
            next_pc = args[0]
            self.tick()

        elif op == Opcode.RET:
            sp = self.dp.read_reg("SP") + 1
            self.dp.write_reg("SP", sp)
            next_pc = self.dp.memory[sp]
            self.tick()

        elif op == Opcode.PUSH:
            sp = self.dp.read_reg("SP")
            val = self.dp.read_reg(args[0])
            self.dp.memory[sp] = val
            self.dp.write_reg("SP", sp - 1)
            self.tick()

        elif op == Opcode.POP:
            sp = self.dp.read_reg("SP") + 1
            self.dp.write_reg("SP", sp)
            val = self.dp.memory[sp]
            self.dp.write_reg(args[0], val)
            self.tick()

        # Порты ввода/вывода

        elif op == Opcode.OUT:
            val = self.dp.read_reg(args[1])
            if args[0] == 1:
                self.dp.port_1_out.append(val)
            self.tick()

        elif op == Opcode.IN:
            val = self.dp.port_0_in.pop(0) if self.dp.port_0_in else 0
            self.dp.write_reg(args[0], val)
            self.tick()

        # Прерывания

        elif op == Opcode.IRET:
            sp = self.dp.read_reg("SP")
            sp += 1
            self.dp.status_register = self.dp.memory[sp]
            sp += 1
            next_pc = self.dp.memory[sp]
            self.dp.write_reg("SP", sp)
            self.tick()

        elif op == Opcode.EI:
            self.dp.flag_ie = 1
            self.tick()

        elif op == Opcode.DI:
            self.dp.flag_ie = 0
            self.tick()

        # Иное

        elif op == Opcode.HLT:
            self.dp.flag_p = 0
            self.is_halted = True
            self.tick()

        # Обновляем PC

        self.dp.write_reg("PC", next_pc)
        self.instruction_counter += 1

        # Interuption Fetch
        
        if self.dp.irq:
            self.handle_interrupt()

    # Обработка прерывания

    def handle_interrupt(self, vector_address: int = 1):

        sp = self.dp.read_reg("SP")

        # Сохраняем текущий адрес возврата в стек

        current_pc = self.dp.read_reg("PC")
        self.dp.memory[sp] = current_pc
        sp -= 1

        # Кладём регистр состояния PS со всеми флагами в стек

        self.dp.memory[sp] = self.dp.status_register
        sp -= 1
        self.dp.write_reg("SP", sp)

        # Аппаратно запрещаем новые прерывания

        self.dp.flag_ie = 0

        # Сбрасываем "готовность" со стороны ВУ

        self.dp.dev_signal = 0

        # Переключаемся на адрес вектора прерывания

        self.dp.write_reg("PC", vector_address)
        self.tick()



        