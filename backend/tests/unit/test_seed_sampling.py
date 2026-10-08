from collections import Counter
from random import Random

import pytest

from app.seed.reference import CATEGORIES, COUNTRY_WEIGHTS, PRODUCT_LINES
from app.seed.sampling import WeightedPicker, apportion


def test_picker_follows_the_weights() -> None:
    picker = WeightedPicker(["a", "b", "c"], [70, 20, 10])
    rng = Random(1)

    counts = Counter(picker.pick(rng) for _ in range(20_000))

    assert 0.68 < counts["a"] / 20_000 < 0.72
    assert 0.18 < counts["b"] / 20_000 < 0.22
    assert 0.08 < counts["c"] / 20_000 < 0.12


def test_picker_never_picks_an_item_with_zero_weight() -> None:
    picker = WeightedPicker(["never", "always"], [0, 1])
    rng = Random(2)

    assert {picker.pick(rng) for _ in range(1_000)} == {"always"}


def test_picker_can_be_limited_to_a_prefix() -> None:
    picker = WeightedPicker(list(range(10)), [1] * 10)
    rng = Random(3)

    assert {picker.pick(rng, among_first=3) for _ in range(1_000)} == {0, 1, 2}


def test_picker_is_deterministic_for_a_seed() -> None:
    picker = WeightedPicker(list(range(100)), list(range(1, 101)))

    first, second = Random(42), Random(42)
    picks = [picker.pick(first) for _ in range(50)]

    assert picks == [picker.pick(second) for _ in range(50)]
    assert len(set(picks)) > 1


@pytest.mark.parametrize("among_first", [0, 4])
def test_picker_rejects_a_prefix_outside_the_list(among_first: int) -> None:
    picker = WeightedPicker(["a", "b", "c"], [1, 1, 1])

    with pytest.raises(ValueError, match="among_first"):
        picker.pick(Random(4), among_first=among_first)


@pytest.mark.parametrize(("items", "weights"), [([], []), (["a"], [1, 2])])
def test_picker_rejects_empty_or_mismatched_weights(items: list[str], weights: list[int]) -> None:
    with pytest.raises(ValueError, match="same length"):
        WeightedPicker(items, weights)


def test_apportion_rounds_to_the_largest_remainders() -> None:
    assert apportion([1, 1, 1], 10) == [4, 3, 3]
    assert apportion([0.5, 0.3, 0.2], 7) == [4, 2, 1]
    assert apportion([2, 1], 0) == [0, 0]


def test_reference_countries_are_uppercase_iso_codes_with_a_dominant_few() -> None:
    assert len(COUNTRY_WEIGHTS) == 20
    assert all(len(code) == 2 and code.isupper() for code in COUNTRY_WEIGHTS)
    top_three = sorted(COUNTRY_WEIGHTS.values(), reverse=True)[:3]
    assert 0.4 < sum(top_three) / sum(COUNTRY_WEIGHTS.values()) < 0.55


def test_every_category_has_enough_distinct_product_names_for_the_full_catalog() -> None:
    # Product names are line x noun; the full scale has 1,000 products.
    for category in CATEGORIES:
        share = category.catalog_share / sum(c.catalog_share for c in CATEGORIES)
        assert len(PRODUCT_LINES) * len(category.nouns) >= share * 1_000 * 1.2, category.name
