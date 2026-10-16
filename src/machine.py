import argparse
import json
import logging
import struct
import sys
from pathlib import Path

from controlunit import ControlUnit
from datapath import DataPath

# Загружает бинарник с диска и запускает процессор


def load_sources(listing_file: str) -> dict[int, str]:
    sources = {}

    for line in Path(listing_file).read_text(encoding="utf-8").splitlines():
        parts = line.split(" - ", 2)
        if len(parts) == 3 and "  ; " in parts[2]:
            sources[int(parts[0])] = parts[2].split("  ; ", 1)[1]

    return sources


def run_simulation(
    binary_file: str,
    schedule: list[tuple[int, str | int]],
    max_ticks: int = 2000,
    sources: dict[int, str] | None = None,
    *,
    cache_enabled: bool = True,
) -> tuple[str, int]:
    dp = DataPath(4096)

    # Читаем 32-битные слова из файла обратно в память

    with Path(binary_file).open("rb") as f:
        for i in range(4096):
            chunk = f.read(4)
            if not chunk:
                break
            word = struct.unpack(">I", chunk)[0]
            dp.memory[i] = word

    cu = ControlUnit(
        dp,
        schedule=schedule,
        sources=sources,
        cache_enabled=cache_enabled,
    )

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
    try:
        while not cu.is_halted and cu.current_tick <= max_ticks:
            cu.tick()
            logging.debug("%s", str(cu))
    except EOFError:
        logging.warning("Ошибка: буфер ввода пуст, но программа запрашивает IN")

    if cu.current_tick >= max_ticks:
        logging.warning("Превышен лимит тактов, процессор принудительно остановлен")

    # Собираем вывод из порта 1

    output_chars = ""
    for c in dp.port_1_out:
        if 32 <= c <= 126 or c == 10:
            output_chars += chr(c)
        else:
            output_chars += f"\\x{c:02x}"

    logging.info(separator)
    logging.info("Процессор остановлен, выполнено тактов: %d", cu.current_tick)
    logging.info("Выполнено инструкций: %d", cu.instruction_counter)
    logging.info("Вывод в порт 1:")

    print("\n" + "=" * 40)
    print(output_chars)
    print("=" * 40 + "\n")

    total_requests = cu.cache.hits + cu.cache.misses
    hit_rate = (cu.cache.hits / total_requests * 100) if total_requests > 0 else 0
    logging.info("Статистика кеш-попаданий:")
    logging.info(
        "Попаданий (Hits): %d | Промахов (Misses): %d | Hit Rate: %.2f%%",
        cu.cache.hits,
        cu.cache.misses,
        hit_rate,
    )

    return output_chars, cu.current_tick


# Точка входа в программу


def main() -> None:
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
        help="Путь к текстовому файлу с входными данными (опционально)",
    )

    parser.add_argument(
        "-t",
        "--ticks",
        type=int,
        default=5000,
        help="Лимит тактов симуляции (по умолчанию 5000)",
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

    # Формируем расписание прерываний из файла

    schedule = []
    if args.input:
        try:
            content = Path(args.input).read_text(encoding="utf-8").strip()
            if content.startswith("["):
                schedule = json.loads(content)
            else:
                current_tick = 50
                for char in content:
                    schedule.append((current_tick, char))
                    current_tick += 100
        except FileNotFoundError:
            print(f"Ошибка: файл ввода '{args.input}' не найден", file=sys.stderr)
            sys.exit(1)

    # Запуск симуляции

    try:
        run_simulation(
            args.code,
            schedule,
            max_ticks=args.ticks,
            sources=load_sources(args.listing) if args.listing else None,
            cache_enabled=not args.no_cache,
        )
    except Exception as e:
        print(f"Произошла ошибка во время симуляции: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
