"""Tests for the SCIM filter parser."""

from __future__ import annotations

import pytest
from django.db.models import Q

from django_scim2_server.exceptions import InvalidFilterError
from django_scim2_server.filters import parse_filter

FILTER_MAP = {
    "userName": "scim_username",
    "name.familyName": "user__last_name",
    "active": "active",
    "externalId": "external_id",
}


class TestParseFilter:
    """Tests for parse_filter."""

    def test_eq_string(self) -> None:
        q = parse_filter('userName eq "john"', FILTER_MAP)
        assert q == Q(scim_username__iexact="john")

    def test_eq_boolean(self) -> None:
        q = parse_filter("active eq true", FILTER_MAP)
        assert q == Q(active__exact=True)

    def test_ne(self) -> None:
        q = parse_filter('userName ne "john"', FILTER_MAP)
        assert q == ~Q(scim_username__iexact="john")

    def test_co(self) -> None:
        q = parse_filter('userName co "oh"', FILTER_MAP)
        assert q == Q(scim_username__icontains="oh")

    def test_sw(self) -> None:
        q = parse_filter('userName sw "jo"', FILTER_MAP)
        assert q == Q(scim_username__istartswith="jo")

    def test_ew(self) -> None:
        q = parse_filter('userName ew "hn"', FILTER_MAP)
        assert q == Q(scim_username__iendswith="hn")

    def test_pr(self) -> None:
        q = parse_filter("externalId pr", FILTER_MAP)
        assert q == Q(external_id__isnull=False) & ~Q(external_id="")

    def test_and(self) -> None:
        q = parse_filter('userName eq "john" and active eq true', FILTER_MAP)
        expected = Q(scim_username__iexact="john") & Q(active__exact=True)
        assert q == expected

    def test_or(self) -> None:
        q = parse_filter('userName eq "john" or userName eq "jane"', FILTER_MAP)
        expected = Q(scim_username__iexact="john") | Q(scim_username__iexact="jane")
        assert q == expected

    def test_not(self) -> None:
        q = parse_filter('not userName eq "john"', FILTER_MAP)
        assert q == ~Q(scim_username__iexact="john")

    def test_parentheses(self) -> None:
        q = parse_filter(
            '(userName eq "john" or userName eq "jane") and active eq true',
            FILTER_MAP,
        )
        expected = (
            Q(scim_username__iexact="john") | Q(scim_username__iexact="jane")
        ) & Q(active__exact=True)
        assert q == expected

    def test_empty_filter(self) -> None:
        q = parse_filter("", FILTER_MAP)
        assert q == Q()

    def test_unknown_attribute_raises(self) -> None:
        with pytest.raises(InvalidFilterError, match="Unknown attribute"):
            parse_filter('unknownAttr eq "x"', FILTER_MAP)

    def test_invalid_syntax_raises(self) -> None:
        with pytest.raises(InvalidFilterError):
            parse_filter('userName eq eq "x"', FILTER_MAP)

    def test_gt_lt(self) -> None:
        q = parse_filter("externalId gt 5", {"externalId": "external_id"})
        assert q == Q(external_id__gt=5)

    def test_null_value(self) -> None:
        q = parse_filter("externalId eq null", FILTER_MAP)
        assert q == Q(external_id__exact=None)

    def test_float_value(self) -> None:
        q = parse_filter("externalId gt 3.14", {"externalId": "external_id"})
        assert q == Q(external_id__gt=3.14)

    def test_unexpected_character_raises(self) -> None:
        with pytest.raises(InvalidFilterError, match="Unexpected character"):
            parse_filter("userName eq @bad", FILTER_MAP)

    def test_trailing_tokens_raises(self) -> None:
        with pytest.raises(InvalidFilterError, match="Unexpected tokens"):
            parse_filter('userName eq "john" "extra"', FILTER_MAP)

    def test_missing_operator_raises(self) -> None:
        with pytest.raises(InvalidFilterError, match="Expected operator"):
            parse_filter('userName "john"', FILTER_MAP)

    def test_unclosed_paren_raises(self) -> None:
        with pytest.raises(InvalidFilterError, match="Expected rparen"):
            parse_filter('(userName eq "john"', FILTER_MAP)

    def test_eq_false(self) -> None:
        q = parse_filter("active eq false", FILTER_MAP)
        assert q == Q(active__exact=False)

    def test_ge_le(self) -> None:
        fm = {"externalId": "external_id"}
        assert parse_filter("externalId ge 5", fm) == Q(external_id__gte=5)
        assert parse_filter("externalId le 5", fm) == Q(external_id__lte=5)
