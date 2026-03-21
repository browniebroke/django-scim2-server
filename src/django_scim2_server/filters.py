"""SCIM 2.0 filter expression parser."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from django.db.models import Q

from django_scim2_server.exceptions import InvalidFilterError

if TYPE_CHECKING:
    from collections.abc import Sequence

# Token types
_TOKEN_RE = re.compile(
    r"""
    (?P<lparen>\()
    |(?P<rparen>\))
    |(?P<string>"(?:[^"\\]|\\.)*")
    |(?P<bool>true|false)
    |(?P<null>null)
    |(?P<number>-?\d+(?:\.\d+)?)
    |(?P<op>eq|ne|co|sw|ew|gt|ge|lt|le|pr)\b
    |(?P<logic>and|or|not)\b
    |(?P<attr>[a-zA-Z_][\w.]*)
    """,
    re.VERBOSE | re.IGNORECASE,
)


class _Token:
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value

    def __repr__(self) -> str:
        return f"Token({self.kind}, {self.value!r})"


def _tokenize(expression: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while pos < len(expression):
        if expression[pos].isspace():
            pos += 1
            continue
        m = _TOKEN_RE.match(expression, pos)
        if not m:
            raise InvalidFilterError(f"Unexpected character at position {pos}")
        kind = m.lastgroup
        if kind is None:  # pragma: no cover
            raise InvalidFilterError(f"Unexpected token at position {pos}")
        value = m.group()
        # Normalise keyword tokens to lowercase
        if kind in ("op", "logic", "bool"):
            value = value.lower()
        tokens.append(_Token(kind, value))
        pos = m.end()
    return tokens


class _Parser:
    """Recursive descent parser for SCIM filter expressions."""

    def __init__(self, tokens: Sequence[_Token], filter_map: dict[str, str]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.filter_map = filter_map

    def _peek(self) -> _Token | None:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return None

    def _advance(self) -> _Token:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def _expect(self, kind: str) -> _Token:
        tok = self._peek()
        if tok is None or tok.kind != kind:
            expected = kind
            got = tok.kind if tok else "end of input"
            raise InvalidFilterError(f"Expected {expected}, got {got}")
        return self._advance()

    def parse(self) -> Q:
        q = self._or_expr()
        if self.pos < len(self.tokens):
            raise InvalidFilterError("Unexpected tokens after filter expression")
        return q

    def _or_expr(self) -> Q:
        left = self._and_expr()
        while (tok := self._peek()) and tok.kind == "logic" and tok.value == "or":
            self._advance()
            right = self._and_expr()
            left = left | right
        return left

    def _and_expr(self) -> Q:
        left = self._not_expr()
        while (tok := self._peek()) and tok.kind == "logic" and tok.value == "and":
            self._advance()
            right = self._not_expr()
            left = left & right
        return left

    def _not_expr(self) -> Q:
        tok = self._peek()
        if tok and tok.kind == "logic" and tok.value == "not":
            self._advance()
            operand = self._atom()
            return ~operand
        return self._atom()

    def _atom(self) -> Q:
        tok = self._peek()
        if tok and tok.kind == "lparen":
            self._advance()
            q = self._or_expr()
            self._expect("rparen")
            return q
        return self._comparison()

    def _comparison(self) -> Q:
        attr_tok = self._expect("attr")
        attr_name = attr_tok.value

        op_tok = self._peek()
        if op_tok is None or op_tok.kind != "op":
            raise InvalidFilterError(f"Expected operator after '{attr_name}'")
        self._advance()
        op = op_tok.value

        if op == "pr":
            orm_field = self._resolve_attr(attr_name)
            return Q(**{f"{orm_field}__isnull": False}) & ~Q(**{orm_field: ""})

        value = self._parse_value()
        orm_field = self._resolve_attr(attr_name)
        return self._build_q(orm_field, op, value)

    def _parse_value(self) -> str | bool | float | None:
        tok = self._advance()
        if tok.kind == "string":
            return tok.value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        if tok.kind == "bool":
            return tok.value == "true"
        if tok.kind == "null":
            return None
        if tok.kind == "number":
            return float(tok.value) if "." in tok.value else int(tok.value)
        raise InvalidFilterError(f"Expected value, got {tok.kind}")

    def _resolve_attr(self, attr_name: str) -> str:
        orm_field = self.filter_map.get(attr_name)
        if orm_field is None:
            raise InvalidFilterError(f"Unknown attribute: {attr_name}")
        return orm_field

    def _build_q(self, field: str, op: str, value: object) -> Q:
        lookup_map: dict[str, str] = {
            "eq": "iexact" if isinstance(value, str) else "exact",
            "ne": "iexact" if isinstance(value, str) else "exact",
            "co": "icontains",
            "sw": "istartswith",
            "ew": "iendswith",
            "gt": "gt",
            "ge": "gte",
            "lt": "lt",
            "le": "lte",
        }
        lookup = lookup_map.get(op)
        if lookup is None:
            raise InvalidFilterError(f"Unsupported operator: {op}")

        q = Q(**{f"{field}__{lookup}": value})
        if op == "ne":
            q = ~q
        return q


def parse_filter(expression: str, filter_map: dict[str, str]) -> Q:
    """Parse a SCIM filter expression and return a Django Q object."""
    tokens = _tokenize(expression)
    if not tokens:
        return Q()
    parser = _Parser(tokens, filter_map)
    return parser.parse()
