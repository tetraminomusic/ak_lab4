import argparse
import json
import logging
import struct
import sys
from pathlib import Path

from controlunit import ControlUnit
from datapath import DataPath
from isa import WORD_SIZE

DEFAULT_TICKS = 5000
DEFAULT_TICKS_AFTER_INPUT = 20000
TEXT_INPUT_START = 50
TEXT_INPUT_PERIOD = 1500


# Загружает бинарник с диска и запускает процессор


def load_sources(listing_file: str) -> dict[int, str]:
    sources = {}

    for line in Path(listing_file).read_text(encoding="utf-8").splitlines():
        parts = line.split(" - ", 2)
        if len(parts) == 3 and "  ; " in parts[2]:
            # Собираем словарик вида адрес - выражение

            sources[int(parts[0])] = parts[2].split("  ; ", 1)[1]

    return sources


# Загружает машинные слова в память и запускает цикл тактов


def run_simulation(
    binary_file: str,
    schedule: list[tuple[int, str | int]],
    max_ticks: int = 2000,
    sources: dict[int, str] | None = None,
    *,
    cache_enabled: bool = True,
) -> tuple[str, int]:

    # Проверяем лимит тактов по неотрицательности

    if max_ticks < 0:
        raise ValueError("Лимит тактов не может быть отрицательным")

    dp = DataPath(4096)

    # Читаем бинарик

    capacity = len(dp.memory) * WORD_SIZE

    with Path(binary_file).open("rb") as f:
        image = f.read(capacity + 1)

    # проверяем его размер

    if not image or len(image) > capacity or len(image) % WORD_SIZE:
        raise ValueError("Бинарник должен содержать от 1 до 4096 полных 32-битных слов")

    # разбиваем на 32 битные слова по биг эндину

    for i, (word,) in enumerate(struct.iter_unpack(">I", image)):
        dp.memory[i] = word

    cu = ControlUnit(
        dp,
        schedule=schedule,
        sources=sources,
        cache_enabled=cache_enabled,
    )

    # Визуальная туфта и тому подобные непотребства

    logging.info("\nЗапуск процесса by tetramino")

    register_names = " ".join(f"{f'R{i}':>5}" for i in range(16))

    header = (
        f"| {'TICK':^6} "
        f"| {'STEP':<9} "
        f"| {'PC':^5} "
        f"| {'HEX CODE':^8} "
        f"| {'INSTRUCTION':<22} "
        f"| {'SP':^6} "
        f"| {'NZVC':^6} "
        f"| {'CACHE':^9} "
        f"| {'INT':^4} "
        f"| {register_names} "
        f"| {'SOURCE'}"
    )

    separator = "-" * len(header)

    logging.debug(separator)
    logging.debug(header)
    logging.debug(separator)

    # Главный цикл симуляции

    while not cu.is_halted and cu.current_tick < max_ticks:
        # Продвигаемся по одному циклу тг

        cu.tick()
        if logging.getLogger().isEnabledFor(logging.DEBUG):
            logging.debug("%s", str(cu))

    if cu.fault is not None:
        raise RuntimeError(cu.fault)
    if not cu.is_halted:
        logging.warning("Достигнут лимит тактов, процессор принудительно остановлен")

    # Собираем вывод из порта 1

    output_chars = "".join(
        chr(c) if 32 <= c <= 126 or c == 10 else f"\\x{c:02x}" for c in dp.port_1_out
    )

    logging.info(separator)
    logging.info("Процессор остановлен, выполнено тактов: %d", cu.current_tick)
    logging.info("Выполнено инструкций: %d", cu.instruction_counter)
    logging.info("Вывод в порт 1:")

    print("\n" + "=" * 40)
    print(output_chars)
    print("=" * 40 + "\n")

    # А тута у нас кеш

    total_requests = cu.cache.hits + cu.cache.misses
    hit_rate = (cu.cache.hits / total_requests * 100) if total_requests > 0 else 0
    logging.info("Статистика кеш-попаданий:")
    logging.info(
        "Попаданий: %d | Промахов: %d | Hit Rate: %.2f%%",
        cu.cache.hits,
        cu.cache.misses,
        hit_rate,
    )

    return output_chars, cu.current_tick


# Превращает текстовый ввод в события по такту и значению


def load_input_schedule(path: Path) -> list[tuple[int, str | int]]:
    content = path.read_text(encoding="utf-8")

    # Проверяем, что весь текст состоит из символов

    if path.suffix.lower() != ".json":
        if not content.isascii():
            raise ValueError("Текстовый ввод должен содержать только ASCII-символы")
        return [
            (TEXT_INPUT_START + TEXT_INPUT_PERIOD * i, char)
            for i, char in enumerate(content)
        ]

    events = json.loads(content)
    if not isinstance(events, list):
        raise TypeError("Расписание должно быть списком пар [такт, значение]")

    schedule: list[tuple[int, str | int]] = []

    # Разбиваем JSON на пары вида [такт, значение]

    for event in events:
        if not isinstance(event, list) or len(event) != 2:
            raise ValueError("Событие должно иметь вид [такт, значение]")

        tick, value = event
        if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0:
            raise ValueError(f"Некорректный такт события: {tick}")

        if isinstance(value, str):
            if len(value) != 1 or not value.isascii():
                raise ValueError("В событии ожидается один ASCII-символ")

        elif (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not -(1 << 31) <= value <= 0xFFFF_FFFF
        ):
            raise ValueError("Числовой токен должен помещаться в машинное слово")

        schedule.append((tick, value))

    return schedule


# Точка входа в программу


def main() -> None:

    # формальности для запуска приложения с определёнными флагами

    parser = argparse.ArgumentParser(
        description="Симулятор RISC-процессора by tetramino",
    )

    parser.add_argument(
        "-c",
        "--code",
        required=True,
        help="Путь к бинарному файлу с машинным кодом (.bin)",
    )

    parser.add_argument(
        "-i",
        "--input",
        default=None,
        help="Текстовый ввод или точное расписание в файле json",
    )

    parser.add_argument(
        "-t",
        "--ticks",
        type=int,
        help=f"Лимит тактов (без ввода {DEFAULT_TICKS}, "
        f"с вводом {DEFAULT_TICKS_AFTER_INPUT} после последнего события)",
    )

    parser.add_argument(
        "-l",
        "--listing",
        default=None,
        help="Путь к листингу: в журнал попадут соответствующие строки исходника",
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Отключить кеш: каждое обращение в память стоит 10 тактов",
    )

    args = parser.parse_args()

    # Оставляем чистый формат логов

    logging.basicConfig(level=logging.DEBUG, format="%(message)s")

    # Запуск самой симуляции

    try:
        # Добавляем список событий, если был флажок i

        schedule = load_input_schedule(Path(args.input)) if args.input else []
        max_ticks = args.ticks

        # Выборка лимита тактов

        if max_ticks is None:
            max_ticks = (
                max(tick for tick, _ in schedule) + DEFAULT_TICKS_AFTER_INPUT
                if schedule
                else DEFAULT_TICKS
            )

        # Запуск самой симуляции

        run_simulation(
            args.code,
            schedule,
            max_ticks=max_ticks,
            sources=load_sources(args.listing) if args.listing else None,
            cache_enabled=not args.no_cache,
        )
    except Exception as e:
        print(f"Произошла ошибка во время симуляции: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
