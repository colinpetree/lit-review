"""Whether two paper titles plausibly belong to the same paper.

Used to double-check an abstract looked up by DOI: if the DOI on a paper points
at a different paper in some source (a merged record, a book vs one of its
chapters), the abstract that comes back would be the wrong one, so it's
dropped when the titles share too few words.

Deliberately lenient: formatting differences (case, punctuation, dashes,
HTML tags, subscripts like H_2 vs H2, accents) and a missing or extra subtitle
all pass. A wrongly skipped abstract costs the user a manual paste; a wrongly
accepted one puts another paper's abstract on theirs, which is worse and easy
to miss.
"""

import re
import unicodedata

# Share of the shorter title's words that must also be in the other title.
# Checked against real data: across 284 source replies for 150 papers, every
# genuine match scored 0.80 or higher (the lowest were formatting quirks like
# "H 2 O" vs "H2O"), while clearly different papers score near 0.
MIN_OVERLAP = 0.5

_STOP_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on", "or", "the", "to", "with",
}


# A word is a run of letters/digits, except Chinese, Japanese and Korean text,
# which has no spaces between words, so each character counts as its own word.
_CJK = "一-鿿぀-ヿ가-힯"
_WORD_RE = re.compile(rf"[{_CJK}]|[^\W_{_CJK}]+")


def _words(title):
    text = re.sub(r"<[^>]+>", " ", title or "")
    # NFKD turns subscripts/superscripts into plain digits and splits accents off.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    # H_2, CO_{2}, x^2 -> h2, co2, x2
    text = re.sub(r"[_{}^]", "", text)
    return {w for w in _WORD_RE.findall(text) if w not in _STOP_WORDS}


# The markup APIs leave in titles (italics, sub/superscripts, MathML, line breaks).
# Only these are tags: a bare "<" in a title is a symbol ("x<5 and y>3"), and a
# catch-all <...> pattern would delete the text between two of them.
# HTML tags are matched only bare (<i>, </sub>, <br/>), never with attributes, so
# "a<b and c>d" is left alone; only MathML tags, which do carry attributes, may.
INLINE_TAG_RE = re.compile(
    r"</?(?:i|b|u|em|strong|sub|sup|small|sc|span|br|p|italic|bold)\s*/?>|</?(?:mml:[a-z]+|math)\b[^<>]*>",
    re.I,
)


def title_key(title):
    """A title reduced to what identifies the paper, for matching the same paper
    across sources: markup, accents, case, punctuation and spacing are gone, so
    "Coral <i>growth</i> modeling" (OpenAlex) and "Coral growth modeling." (PubMed)
    give the same key. '' for a title with nothing to match on, which callers must
    not treat as a match."""
    if not isinstance(title, str):
        return ""
    # Tags go without a space, so H<sub>2</sub>O is h2o, as plain text H2O is.
    text = INLINE_TAG_RE.sub("", title)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = re.sub(r"[_{}^]", "", text)
    # "+" and "#" stay, since they tell titles apart ("C++" and "C", "Na+" and "Na").
    return re.sub(r"[^\w+#]+", " ", text).strip()


def overlap(stored_title, found_title):
    """Share of the shorter title's meaningful words found in the other, or
    None if either title has none to compare."""
    a, b = _words(stored_title), _words(found_title)
    if not a or not b:
        return None
    return len(a & b) / min(len(a), len(b))


def titles_match(stored_title, found_title):
    """False only when the titles clearly differ; True if they're similar or
    there's nothing to compare."""
    score = overlap(stored_title, found_title)
    return score is None or score >= MIN_OVERLAP
