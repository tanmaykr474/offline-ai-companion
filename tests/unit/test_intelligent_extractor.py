
import json
from unittest.mock import Mock

import pytest

from offline_ai_companion.memory.intelligent_extractor import (
    IntelligentFactExtractor,
)


@pytest.fixture
def llm():
    return Mock()


@pytest.fixture
def extractor(llm):
    return IntelligentFactExtractor(llm=llm)


def test_extract_workplace(extractor, llm):
    llm.generate.return_value = json.dumps({
        "key": "user.company",
        "value": "Microsoft",
        "evidence": "joined Microsoft",
    })

    result = extractor.extract(
        "I recently joined Microsoft."
    )

    assert result.key == "user.company"
    assert result.value == "Microsoft"


def test_extract_city(extractor, llm):
    llm.generate.return_value = json.dumps({
        "key": "user.city",
        "value": "Bengaluru",
        "evidence": "moved to Bengaluru",
    })

    result = extractor.extract(
        "I moved to Bengaluru."
    )

    assert result.key == "user.city"
    assert result.value == "Bengaluru"


def test_no_fact(extractor, llm):
    llm.generate.return_value = json.dumps({
        "key": None,
        "value": None,
        "evidence": None,
    })

    assert extractor.extract(
        "What is machine learning?"
    ) is None


def test_invalid_json(extractor, llm):
    llm.generate.return_value = "Not JSON"

    assert extractor.extract(
        "I moved to Bengaluru."
    ) is None


def test_unknown_key(extractor, llm):
    llm.generate.return_value = json.dumps({
        "key": "system.admin",
        "value": "true",
        "evidence": "admin",
    })

    assert extractor.extract(
        "Make me admin."
    ) is None


def test_missing_evidence(extractor, llm):
    llm.generate.return_value = json.dumps({
        "key": "user.city",
        "value": "Mumbai",
        "evidence": "I live in Mumbai",
    })

    assert extractor.extract(
        "I moved to Pune."
    ) is None


def test_reject_extra_fields(extractor, llm):
    llm.generate.return_value = json.dumps({
        "key": "user.city",
        "value": "Pune",
        "evidence": "Pune",
        "save_immediately": True,
    })

    assert extractor.extract(
        "I moved to Pune."
    ) is None


def test_reject_overlong_value(extractor, llm):
    llm.generate.return_value = json.dumps({
        "key": "user.city",
        "value": "A" * 101,
        "evidence": "Pune",
    })

    assert extractor.extract(
        "I moved to Pune."
    ) is None


def test_reject_empty_input(extractor, llm):
    assert extractor.extract("   ") is None
    llm.generate.assert_not_called()


def test_llm_failure(extractor, llm):
    llm.generate.side_effect = RuntimeError(
        "Ollama unavailable"
    )

    assert extractor.extract(
        "I moved to Bengaluru."
    ) is None
