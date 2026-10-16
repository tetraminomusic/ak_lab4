from isa import WORD_SIZE

# Одна физическая строка в кеш памяти
# При реализации кеша буду использовать Direct-Mapped кеш, мол, прямое отображение и тд. Реализуем через остаток от деления на 8


class CacheLine:
    def __init__(self, block_size: int = 4) -> None:
        self.valid = False  # Флаг - есть ли в строке реальные и актуальные данные
        self.tag: int | None = None  # Номер блока в оперативной памяти
        self.data = [0] * block_size  # Блок 32-битных значений из этого блока


# Сам великий и неповторимый кеш


class Cache:
    def __init__(
        self,
        memory: list[int],
        num_lines: int = 8,
        block_size: int = 4,
        *,
        enabled: bool = True,
    ) -> None:

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

    # Заполнение строки - это одно обращение к памяти, оно стоит 10 тактов
    # независимо от того, сколько слов в блоке

    def fill_cost(self) -> int:
        return 10

    # Байтовый адрес раскладывается на номер блока и номер слова внутри блока

    def split_address(self, addr: int) -> tuple[int, int]:
        block, offset_bytes = divmod(addr, self.block_size * WORD_SIZE)
        return block, offset_bytes // WORD_SIZE

    # Функция чтения, возвращает [прочитанное значение, затраченные такты]

    def read(self, addr: int) -> tuple[int, int]:
        if not self.enabled:
            self.misses += 1
            self.last_status = "OFF (10) "
            return self.memory[addr // WORD_SIZE], 10

        block, offset = self.split_address(addr)
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

        base_word = block * self.block_size

        line.valid = True
        line.tag = block
        line.data = self.memory[base_word : base_word + self.block_size]

        return line.data[offset], wait_ticks

    # сквозная запись. Возвращает затраченное время на запись

    def write(self, addr: int, val: int) -> int:
        if not self.enabled:
            self.memory[addr // WORD_SIZE] = val
            self.last_status = "OFF (10) "
            return 10

        block, offset = self.split_address(addr)
        line = self.lines[block % self.num_lines]

        # Пишем в ОЗУ

        self.memory[addr // WORD_SIZE] = val

        # Если в кеше лежал адрес, который мы хотели записать

        if line.valid and line.tag == block:
            line.data[offset] = val

        self.last_status = "WRITE(10)"
        return 10
