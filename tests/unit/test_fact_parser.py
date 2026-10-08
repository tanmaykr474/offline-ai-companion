
import pytest

from offline_ai_companion.memory.fact_parser import FactParser


@pytest.fixture
def parser():
    return FactParser()


def test_save_favorite_language(parser):
    result = parser.parse(
        "My favorite language is Python"
    )

    assert result.action == "set"
    assert result.key == "user.favorite_language"
    assert result.value == "Python"


def test_get_favorite_language(parser):
    result = parser.parse(
        "What is my favorite language?"
    )

    assert result.action == "get"
    assert result.key == "user.favorite_language"


def test_aliases_use_same_key(parser):
    first = parser.parse(
        "My favorite programming language is Java"
    )
    second = parser.parse(
        "What is my favorite language?"
    )

    assert first.key == second.key


@pytest.mark.parametrize(
    "query",
    [
        "My favorite food is what?",
        "My favorite color is unknown?",
        "My city is which?",
    ],
)
def test_questions_never_update_facts(parser, query):
    result = parser.parse(query)

    assert result is None or result.action != "set"


def test_unrecognized_statement(parser):
    assert parser.parse(
        "Explain Python programming"
    ) is None



def test_natural_food_declaration(parser):
    result = parser.parse("I love eating Biryani")

    assert result.action == "set"
    assert result.key == "user.favorite_food"
    assert result.value == "Biryani"


def test_natural_workplace_declaration(parser):
    result = parser.parse("I work at Infosys")

    assert result.action == "set"
    assert result.key == "user.company"
    assert result.value == "Infosys"


def test_natural_city_declaration(parser):
    result = parser.parse("I live in Pune")

    assert result.action == "set"
    assert result.key == "user.city"
    assert result.value == "Pune"


@pytest.mark.parametrize(
    "question, expected_key",
    [
        ("What food do I like?", "user.favorite_food"),
        (
            "Which programming language is my favorite?",
            "user.favorite_language",
        ),
        ("Where do I work?", "user.company"),
        ("Where do I live?", "user.city"),
        ("Where am I from?", "user.hometown"),
        ("My favorite food is what?", "user.favorite_food"),
    ],
)
def test_natural_fact_questions(
    parser,
    question,
    expected_key,
):
    result = parser.parse(question)

    assert result is not None
    assert result.action == "get"
    assert result.key == expected_key


def test_ambiguous_love_statement_is_not_saved(parser):
    assert parser.parse("I love Biryani") is None


def test_question_does_not_update_workplace(parser):
    result = parser.parse("Where do I work?")

    assert result.action == "get"


@pytest.mark.parametrize(
    "message, expected_key, expected_value",
    [
        (
            "I recently joined Microsoft",
            "user.company",
            "Microsoft",
        ),
        (
            "I recently joined Microsoft'",
            "user.company",
            "Microsoft",
        ),
        (
            "I joined Microsoft as a software engineer",
            "user.company",
            "Microsoft",
        ),
        (
            "I moved to Bengaluru",
            "user.city",
            "Bengaluru",
        ),
        (
            "I just moved to Pune",
            "user.city",
            "Pune",
        ),
    ],
)
def test_natural_updates(
    parser,
    message,
    expected_key,
    expected_value,
):
    result = parser.parse(message)

    assert result is not None
    assert result.action == "set"
    assert result.key == expected_key
    assert result.value == expected_value
