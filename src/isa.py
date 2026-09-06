from enum import IntEnum

class Opcode(IntEnum):

    # Работа с памаятью + регистры

    LDI = 0x01              # 0000 0001 - Load Immediate: LDI R1, 10 (10 -> R1)
    LD  = 0x02              # 0000 0010 - Load: LD R1, R2, offset (R1 -> Mem[R2+offset])
    ST  = 0x03              # 0000 0011 - Store: ST R1, R2, offset (Mem[R2+offset] -> R1)

    # Арифметика (чисто регистры)

    ADD = 0x04              # 0000 0100 - ADD R1, R2, R3 (R2 + R3 -> R1)
    SUB = 0x05              # 0000 0101 - SUB R1, R2, R3 (R2 - R3 -> R1)
    MUL = 0x06              # 0000 0110 - MUL R1, R2, R3 (R2 * R3 -> R1)
    DIV = 0x07              # 0000 0111 - DIV R1, R2, R3 (R2 / R3 -> R1)
    MOD = 0x08              # 0000 1000 - MOD R1, R2, R3 (R2 % R3 -> R1)
    INC = 0x09              # 0000 1001 - INC R1 (R1 + 1 -> R1)
    DEC = 0x0A              # 0000 1010 - DEC R1 (R1 - 1 -> R1)
    CMP = 0x0B              # 0000 1011 - CMP R1, R2 (R1 - R2 -> NZVC)

    # Логические операции

    AND = 0x0C              # 0000 1100 - AND R1, R2, R3 (R2 & R3 -> R1)
    OR  = 0x0D              # 0000 1101 - OR R1, R2, R3 (R2 | R3 -> R1)
    XOR = 0x0E              # 0000 1110 - XOR R1, R2, R3 (R2 ^ R3 -> R1)
    NOT = 0x0F              # 0000 1111 - NOT R1, R2 (~R2 -> R1)

    # Логические сдвиги

    LSL = 0x10              # 0001 0000 - Logical Shift Left (R2 << R3 -> R1)
    LSR = 0x11              # 0001 0001 - Logical Shift Right (R2 >> R3 -> R1, с нулями)

    # Арифметические сдвиги

    ASL = 0x12              # 0001 0010 - Arithmetic Shift Left (R2 << R3 -> R1, с проверкой V)
    ASR = 0x13              # 0001 0011 - Arithmetic Shift Right (с сохранением знака)

    # Циклические сдвиги (Rotations)
    
    ROL = 0x14              # 0001 0100 - Rotate Left  
    ROR = 0x15              # 0001 0101 - Rotate Right

    # Ветвления

    JMP = 0x16              # 0001 0110 - Безусловный переход
    JZ  = 0x17              # 0001 0111 - Переход, если Z == 1 (Equal)
    JNZ = 0x18              # 0001 1000 - Переход, если Z == 0 (Not Equal)
    JN  = 0x19              # 0001 1001 - Переход, если N == 1 (Negative)
    JNN = 0x1A              # 0001 1010 - Переход, если N == 0 (Not Negative)
    JL  = 0x1B              # 0001 1011 - Переход, если Меньше (N != V)
    JGE = 0x1C              # 0001 1100 - Переход, если Больше или Равно (N == V)
    JC  = 0x1D              # 0001 1101 - Переход, если C == 1
    JNC = 0x1E              # 0001 1110 - Переход, если C == 0
    JV  = 0x1F              # 0001 1111 - Переход, если V == 1
    JNV = 0x20              # 0010 0000 - Переход, если V == 0

    # Функция + Стек

    CALL = 0x21             # 0010 0001 - CALL ADDR: вызов функции: next_pc -> LR; ADDR -> PC
    RET  = 0x22             # 0010 0010 - Возврат из функции: LR -> PC
    PUSH = 0x23             # 0010 0011 - PUSH R1: R1 -> Mem[SP], SP - 1 -> SP
    POP  = 0x24             # 0010 0100 - POP R1: SP + 1 -> SP, MEM[SP] -> R1

    # Порты + прерывания

    IN   = 0x25             # 0010 0101 - IN R1, port_num
    OUT  = 0x26             # 0010 0110 - OUT port_num, R1
    EI   = 0x27             # 0010 0111 - Enable Interrupts (разрешить прерывания: IE = 1)
    DI   = 0x28             # 0010 1000 - Disable Interrupts (запретить прерывания: IE = 0)
    IRET = 0x29             # 0010 1001 - Возврат из прерывания + восстановление флагов: IRA -> PC

    # Прочее

    HLT  = 0x2A             # 0010 1010 - Остановка процессора

# Машинная инструкция процессора

class Instruction:

    # Будет запускаться каждый раз, когда будет создаваться объект класса Instruction
    
    def __init__(self, opcode: Opcode, args: list = None):
        self.opcode = opcode

        # Если аргументов нет, то делаем просто пустой список
        self.args = args if args is not None else []

    # Форматируем так, чтобы красиво отображалось
    
    def __repr__(self):
        args_str = ", ".join(map(str, self.args))
        return f"{self.opcode.name} {args_str}".strip()

    # Упаковывает команду в 32-битное машинное слово:

    def encode(self) -> int:
        op_code_num = int(self.opcode) & 0xFF

        rd = 0
        rs1 = 0
        imm = 0

        # Парсим аргументы

        for arg in self.args:
            if isinstance(arg, str) and arg.startswith("R"):
                reg_num = int(arg.replace("R", ""))
                if rd == 0:
                    rd = reg_num
                else:
                    rs1 = reg_num

            # Если это стек
            
            elif arg == "LR":
                if rd == 0: rd = 13
                else: rs1 = 13
            elif arg == "SP":
                if rd == 0: rd = 12
                else: rs1 = 12

            # Если аргумент это просто число
            
            elif isinstance(arg, int):
                imm = arg & 0xFFFF

        # Склеиваем в 32 битное слово

        word = (op_code_num << 24) | (rd << 20) | (rs1 << 16) | imm

        return word