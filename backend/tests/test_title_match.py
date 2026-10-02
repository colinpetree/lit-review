import pytest

from title_match import overlap, titles_match


@pytest.mark.parametrize(
    "stored, found",
    [
        ("Carbon storage in peatland soils", "Carbon Storage in Peatland Soils"),
        ("Carbon storage in peatland soils", "Carbon storage in peatland soils: a review"),
        ("CO2 capture with amines", "CO<sub>2</sub> capture with amines"),
        ("H2 production", "H_2 production"),
        ("Café culture and the Müller effect", "Cafe culture and the Muller effect"),
        ("Reef-fish larval dispersal", "Reef fish larval dispersal"),
        ("深層学習による画像認識", "深層学習による画像認識の研究"),
    ],
)
def test_same_paper_in_different_formatting_matches(stored, found):
    assert titles_match(stored, found)


@pytest.mark.parametrize(
    "stored, found",
    [
        ("Carbon storage in peatland soils", "Bayesian methods for protein folding"),
        ("Gene expression in zebrafish embryos", "Pump efficiency of centrifugal compressors"),
    ],
)
def test_different_papers_do_not_match(stored, found):
    assert not titles_match(stored, found)


@pytest.mark.parametrize("stored, found", [(None, "A title"), ("A title", None), ("", ""), ("the of and", "A title")])
def test_nothing_to_compare_counts_as_a_match(stored, found):
    assert overlap(stored, found) is None
    assert titles_match(stored, found)


def test_overlap_is_a_share_of_the_shorter_title():
    # Both words of the shorter title are in the longer one.
    assert overlap("solar cells", "perovskite solar cells for tandem devices") == 1.0
    assert overlap("solar cells", "coral reefs") == 0.0
