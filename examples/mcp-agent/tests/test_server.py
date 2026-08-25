"""The tools this project offers, called the way anything else calls a function."""

from server.tools import summarize, word_count


def test_summarizing_keeps_the_first_sentence() -> None:
    assert summarize("One thing. Then another. Then more.") == "One thing."


def test_summarizing_can_keep_more_than_one() -> None:
    assert summarize("One thing. Then another. Then more.", sentences=2) == (
        "One thing. Then another."
    )


def test_counting_words() -> None:
    assert word_count("one two three") == 3
