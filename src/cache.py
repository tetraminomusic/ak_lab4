# Одна физическая строка в кеш памяти
# При реализации кеша буду использовать Direct-Mapped кеш, мол, прямое отображение и тд. Реализуем через остаток от деления на 8


class CacheLine:
    def __init__(self, block_size: int = 4):
        self.valid = False  # Флаг - есть ли в строке реальные и актуальные данные
        self.tag: int | None = None  # Номер блока в оперативной памяти
        self.data = [0] * block_size  # Блок 32-битных значений из этого блока


# Сам великий и неповторимый кеш


class Cache:
    def __init__(
        self,
        memory: list,
        num_lines: int = 8,
        enabled: bool = True,
        block_size: int = 4,
    ):

        # Ссылаемся на ОЗУ

        self.memory = memory
        self.num_lines = num_lines
        self.enabled = enabled
        self.block_size = block_size

        self.lines = [CacheLine(block_size) for _ in range(num_lines)]

        # стата для логирования

        self.hits = 0
        self.misses = 0
        self.last_status = "NONE"

    # Блок тянется из памяти одной пачкой: первое слово стоит полную
    # задержку в 10 тактов, остальные слова блока приходят следом по такту

    def fill_cost(self) -> int:
        return 10 + self.block_size - 1

    # Функция чтения, возвращает [прочитанное значение, затраченные такты]

    def read(self, addr: int) -> tuple[int, int]:
        if not self.enabled:
            self.misses += 1
            self.last_status = "OFF (10) "
            return self.memory[addr], 10

        block, offset = divmod(addr, self.block_size)
        line = self.lines[block % self.num_lines]

        # Попадание

        if line.valid and line.tag == block:
            self.hits += 1
            self.last_status = "HIT (1)"
            return line.data[offset], 1

        # Промах

        self.misses += 1
        wait_ticks = self.fill_cost()
        self.last_status = f"MISS({wait_ticks})"

        base_addr = block * self.block_size

        line.valid = True
        line.tag = block
        line.data = self.memory[base_addr : base_addr + self.block_size]

        return line.data[offset], wait_ticks

    # сквозная запись. Возвращает затраченное время на запись

    def write(self, addr: int, val: int) -> int:
        if not self.enabled:
            self.memory[addr] = val
            self.last_status = "OFF (10) "
            return 10

        block, offset = divmod(addr, self.block_size)
        line = self.lines[block % self.num_lines]

        # Пишем в ОЗУ

        self.memory[addr] = val

        # Если в кеше лежал адрес, который мы хотели записать

        if line.valid and line.tag == block:
            line.data[offset] = val

        self.last_status = "WRITE(10)"
        return 10
