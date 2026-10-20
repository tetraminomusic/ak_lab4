import re

# Класс паскаль строчек


class StringLiteral:
    def __init__(self, text: str) -> None:
        self.text = text

    def __repr__(self) -> str:
        return f'StringLiteral("{self.text}")'


Node = int | str | StringLiteral | list["Node"]


# Функция, нужная для дробления списка на атомарные составляющие


def tokenize(code: str) -> list[str]:
    pattern = r'"[^"]*"|;[^\n]*|[()]|[^\s();"]+|"'
    tokens = re.findall(pattern, code)
    if '"' in tokens:
        raise SyntaxError("Ожидалась закрывающая кавычка")
    return [t for t in tokens if not t.startswith(";")]


# Функция, которая отвечает за приведение к нужным типам данных у атомов списка lisp


def parse_atom(token: str) -> Node:

    # String
    if token.startswith('"') and token.endswith('"'):
        return StringLiteral(token[1:-1])

    # Int

    try:
        return int(token)
    except ValueError:
        pass

    # Всё остальное

    return token


def parse(tokens: list[str]) -> Node:
    if len(tokens) == 0:
        raise SyntaxError("Код оборвался раньше вреемни")

    token = tokens.pop(0)

    if token == "(":
        sub_tree = []
        while len(tokens) > 0 and tokens[0] != ")":
            sub_tree.append(parse(tokens))

        if len(tokens) == 0:
            raise SyntaxError("Ожидалась закрывающая скобка ')'")

        tokens.pop(0)
        return sub_tree

    if token == ")":
        raise SyntaxError("Неожиданная закрывающая скобка ')'")

    return parse_atom(token)
