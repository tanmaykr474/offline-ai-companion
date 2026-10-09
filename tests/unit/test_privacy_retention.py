import json
from datetime import datetime, timedelta, timezone
from threading import Event
from unittest.mock import Mock

import httpx
import pytest

from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.core.conversation import ConversationManager
from offline_ai_companion.core.privacy_policy import (
    allows_storage, contains_secret, debug_text, model_text,
)
from offline_ai_companion.audio.recovery import AudioRecovery
from offline_ai_companion.llm.ollama import OllamaLLM
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.memory.passive_repository import PassiveMemoryRepository
from offline_ai_companion.memory.passive_processor import PassiveMemoryProcessor
from offline_ai_companion.memory.passive_retriever import PassiveMemoryRetriever
from offline_ai_companion.memory.intelligent_extractor import FactProposal
from offline_ai_companion.memory.passive_worker import PassiveMemoryWorker
from offline_ai_companion.scheduler.reminder_scheduler import ReminderScheduler
from offline_ai_companion.tools.memory_tools import MemoryTools
from offline_ai_companion.router.query_router import Route

NOW = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)


@pytest.fixture
def environment(tmp_path):
    database = Database(tmp_path / "privacy.db")
    facts = MemoryRepository(database)
    llm = Mock(generate=Mock(return_value="A normal answer."))
    extractor = Mock(extract=Mock(return_value=None))
    assistant = Assistant(memory_tools=MemoryTools(facts), llm=llm, fact_extractor=extractor)
    return assistant, facts, llm, extractor


@pytest.mark.parametrize("text", [
    "My password is dont-save-THIS", "password: dont-save-THIS",
    "OTP 123456", "My PIN is 9876", "api_key=dont-save-THIS",
    "My API key is dont-save-THIS", "access_token: dont-save-THIS",
    "authentication token is dont-save-THIS", "refresh-token=dont-save-THIS",
    "Bearer dont-save-THIS", "sk-dont-save-THIS", "4111 1111 1111 1111",
    "credit card: 4111111111111111", "bank account is 123456789012",
    "ssn: 123-45-6789", "-----BEGIN PRIVATE KEY-----",
])
def test_secrets_blocked_even_with_explicit_storage(environment, text):
    assistant, facts, llm, extractor = environment
    assert contains_secret(text)
    assert not allows_storage(text)
    assert not allows_storage(text, explicit=True)
    assert "can't store" in assistant.process("Remember that " + text)
    assert facts.list_facts() == {}
    assert facts.list_notes() == []
    assert facts.list_tasks() == []
    assert facts.list_reminders() == []
    llm.generate.assert_not_called()
    extractor.extract.assert_not_called()
    assert assistant.conversation_manager.turn_count == 0


@pytest.mark.parametrize("kind", ["fact", "note", "task", "reminder", "update_note", "passive"])
def test_direct_storage_boundaries_block_secrets(environment, kind):
    assistant, facts, _, _ = environment
    text = "api key: dont-save-THIS"
    with pytest.raises(ValueError):
        if kind == "fact":
            facts.set_fact("user.api_key", "dont-save-THIS")
        elif kind == "note":
            facts.add_note(text)
        elif kind == "task":
            facts.add_task(text)
        elif kind == "reminder":
            facts.add_reminder(text, NOW)
        elif kind == "update_note":
            note = facts.add_note("ordinary note")
            facts.update_note(note.id, text)
        else:
            assistant.passive_memory_repository.add("fact", "speaker", text, text)


def test_sensitive_personal_information_requires_explicit_storage(environment):
    assistant, facts, llm, _ = environment
    text = "My medical diagnosis is asthma"
    assert not allows_storage(text)
    assert allows_storage(text, explicit=True)
    passive = PassiveMemoryProcessor(assistant.passive_memory_repository, llm)
    assert passive.process(text) == 0
    llm.generate.assert_not_called()
    assert "Saved your note" in assistant.process("Remember that " + text)
    assert facts.list_notes()[0].content == text
    assert text in assistant._build_memory_context()


@pytest.mark.parametrize("text", ["My name is Alice", "My favorite food is pasta",
                                       "Reset password", "Buy groceries"])
def test_ordinary_personal_information_and_secret_management_tasks_allowed(text):
    assert allows_storage(text, explicit=True)
    assert not contains_secret(text)


@pytest.mark.parametrize("intent", ["set_name", "add_note", "add_task", "add_reminder"])
def test_tools_do_not_bypass_secret_policy(environment, intent):
    _, facts, _, _ = environment
    result = MemoryTools(facts).execute(Route(intent, "password: dont-save-THIS", minutes=2))
    assert "can't store" in result
    assert facts.list_facts() == {}
    assert facts.list_notes() == facts.list_tasks() == facts.list_reminders() == []


def test_generated_and_pending_secret_fact_proposals_cannot_be_saved(environment):
    assistant, facts, _, extractor = environment
    proposal = FactProposal("user.name", "password: dont-save-THIS", "I am Alice")
    extractor.extract.return_value = proposal
    assert "can't store" in assistant.process("I am Alice")
    assert assistant.confirmation_manager.pending is None
    assistant.confirmation_manager.propose(proposal)
    assert "can't store" in assistant.process("Yes")
    assert facts.list_facts() == {}


def test_legacy_secret_data_is_preserved_but_not_in_prompts_or_answers(environment):
    assistant, facts, llm, _ = environment
    with facts.database.connect() as db:
        db.execute("INSERT INTO facts (key, value) VALUES (?, ?)", ("user.name", "password: dont-save-THIS"))
        db.execute("INSERT INTO notes (content) VALUES (?)", ("api_key=dont-save-THIS",))
    assert "dont-save-THIS" not in assistant._build_memory_context()
    assert "dont-save-THIS" not in assistant.process("What is my name?")
    assert "dont-save-THIS" not in assistant.process("Show my notes")
    assert facts.get_fact("user.name") == "password: dont-save-THIS"
    assert facts.list_notes()[0].content == "api_key=dont-save-THIS"
    llm.generate.assert_not_called()


def test_model_transport_redacts_credentials_before_sending():
    requests = []
    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"response": "Okay"})
    with httpx.Client(transport=httpx.MockTransport(transport), trust_env=False) as client:
        llm = OllamaLLM(client=client)
        assert llm.generate("My password is dont-save-THIS") == "Okay"
    assert requests[0]["prompt"] == "[CREDENTIAL CONTENT OMITTED]"


def test_history_and_generated_answers_do_not_retain_credentials(environment):
    assistant, _, llm, _ = environment
    llm.generate.return_value = "api_key=dont-save-THIS"
    assert "dont-save-THIS" not in assistant.process("Explain a compiler")
    assert "dont-save-THIS" not in assistant.conversation_manager.build_context()
    manager = ConversationManager()
    manager.add_turn("My password is dont-save-THIS", "Your diagnosis is private")
    assert manager.get_history()[0].user == "[PRIVATE CONTENT OMITTED]"
    assert manager.get_history()[0].assistant == "[PRIVATE CONTENT OMITTED]"


def test_error_logs_never_include_exception_payloads(environment, caplog, capsys):
    assistant, _, llm, _ = environment
    llm.generate.side_effect = RuntimeError("private prompt dont-save-THIS")
    assistant.process("Explain a compiler")
    AudioRecovery(0).handle_failure("Whisper", RuntimeError("private speech dont-save-THIS"), Event())
    assert "dont-save-THIS" not in caplog.text + capsys.readouterr().out
    assert "RuntimeError" in caplog.text


def test_debug_output_requires_opt_in_and_still_hides_credentials(monkeypatch):
    monkeypatch.delenv("NOVA_PRIVATE_DEBUG", raising=False)
    assert "Alice" not in debug_text("Alice lives in Delhi")
    monkeypatch.setenv("NOVA_PRIVATE_DEBUG", "true")
    assert debug_text("Alice lives in Delhi") == "Alice lives in Delhi"
    assert "dont-save-THIS" not in debug_text("password: dont-save-THIS")


def add_observation(repo, captured_at=NOW):
    return repo.add("preference", "speaker", "Loves playing cricket",
                    "I love playing cricket.", captured_at=captured_at)


def test_retention_disabled_preserves_all_saved_data(environment):
    assistant, facts, _, _ = environment
    passive = PassiveMemoryRepository(facts.database, clock=lambda: NOW)
    add_observation(passive, NOW - timedelta(days=3650))
    facts.set_fact("user.name", "Alice")
    facts.add_note("A note")
    facts.add_task("A task")
    facts.add_reminder("A reminder", NOW)
    assert passive.purge_expired() == 0
    assert len(passive.list_memories()) == 1
    assert facts.get_fact("user.name") == "Alice"
    assert len(facts.list_notes()) == len(facts.list_tasks()) == len(facts.list_reminders()) == 1


def test_expiration_excludes_recall_without_deleting_persistent_rows(environment):
    _, facts, _, _ = environment
    now = NOW
    repo = PassiveMemoryRepository(facts.database, retention_days=1, clock=lambda: now)
    assert add_observation(repo)
    retriever = PassiveMemoryRetriever(repo, facts)
    assert "cricket" in retriever.recall("What sport do I love playing?").response
    now += timedelta(days=1)
    assert repo.list_memories() == []
    assert "don't have" in retriever.recall("What sport do I love playing?").response
    assert len(repo.list_memories(include_expired=True)) == 1
    with facts.database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM passive_memories").fetchone()[0] == 1


def test_purge_affects_only_expired_passive_records(environment):
    _, facts, _, _ = environment
    repo = PassiveMemoryRepository(facts.database, retention_days=1, clock=lambda: NOW)
    add_observation(repo, NOW - timedelta(days=1))
    repo.add("fact", "speaker", "Birthplace is Bihar", "I was born in Bihar.", captured_at=NOW)
    facts.set_fact("user.name", "Alice")
    facts.add_note("A note")
    facts.add_task("A task")
    facts.add_reminder("A reminder", NOW)
    assert repo.purge_expired() == 1
    assert repo.purge_expired() == 0
    assert len(repo.list_memories(include_expired=True)) == 1
    assert facts.get_fact("user.name") == "Alice"
    assert len(facts.list_notes()) == len(facts.list_tasks()) == len(facts.list_reminders()) == 1


def test_retention_timezone_boundary_and_pagination(environment):
    _, facts, _, _ = environment
    repo = PassiveMemoryRepository(facts.database, retention_days=1, clock=lambda: NOW)
    add_observation(repo, (NOW - timedelta(days=1)).astimezone(timezone(timedelta(hours=5, minutes=30))))
    repo.add("fact", "speaker", "Birthplace is Bihar", "I was born in Bihar.", captured_at=NOW)
    assert len(repo.list_memories(category="fact", limit=1, offset=0)) == 1
    assert repo.list_memories(category="preference") == []
    assert repo.list_memories(offset=1) == []


def test_conversation_expiration_uses_injected_clock_and_preserves_recent_turns():
    now = NOW
    manager = ConversationManager(retention_seconds=60, clock=lambda: now)
    manager.add_turn("First", "Old answer")
    now += timedelta(seconds=30)
    manager.add_turn("Second", "Recent answer")
    now += timedelta(seconds=30)
    assert manager.turn_count == 1
    assert "First" not in manager.build_context()
    assert manager.get_history()[0].user == "Second"
    now += timedelta(seconds=30)
    assert manager.get_history() == []


def test_default_history_has_no_age_expiry_and_clear_preserves_persistent_memory(environment):
    assistant, facts, _, _ = environment
    now = NOW
    manager = ConversationManager(clock=lambda: now)
    manager.add_turn("First", "Answer")
    now += timedelta(days=1000)
    assert manager.turn_count == 1
    assistant.conversation_manager = manager
    facts.set_fact("user.name", "Alice")
    assistant.process("Clear conversation")
    assert manager.turn_count == 0
    assert facts.get_fact("user.name") == "Alice"


@pytest.mark.parametrize("component", ["passive", "conversation"])
def test_invalid_retention_configuration_rejected(environment, component):
    with pytest.raises(ValueError):
        if component == "passive":
            PassiveMemoryRepository(environment[1].database, retention_days=-1)
        else:
            ConversationManager(retention_seconds=-1)


def test_expired_observations_are_not_added_to_model_context(environment):
    assistant, facts, _, _ = environment
    repo = PassiveMemoryRepository(facts.database, retention_days=1, clock=lambda: NOW)
    add_observation(repo, NOW - timedelta(days=1))
    assistant.passive_memory_repository = repo
    assert "cricket" not in assistant._build_memory_context()
    assert len(repo.list_memories(include_expired=True)) == 1


def test_worker_rejects_sensitive_speech_before_queue_and_logs_only_error_categories(caplog, capsys):
    attempted = Event()
    processor = Mock()
    def fail(text):
        attempted.set()
        raise RuntimeError("private speech dont-save-THIS")
    processor.process.side_effect = fail
    worker = PassiveMemoryWorker(processor)
    worker.start()
    try:
        assert not worker.submit("My password is dont-save-THIS")
        assert not worker.submit("My diagnosis is asthma")
        assert worker.submit("An ordinary accepted statement")
        assert attempted.wait(3)
    finally:
        assert worker.stop(timeout=3)
    assert worker.queue.unfinished_tasks == 0
    assert "dont-save-THIS" not in caplog.text + capsys.readouterr().out
    assert "RuntimeError" in caplog.text


def test_scheduler_errors_do_not_expose_reminder_or_exception_contents(environment, caplog):
    _, facts, _, _ = environment
    facts.add_reminder("A private personal reminder", NOW)
    announce = Mock(side_effect=RuntimeError("private reminder dont-save-THIS"))
    scheduler = ReminderScheduler(facts, announce, clock=lambda: NOW)
    assert scheduler.check_due() == 0
    assert "dont-save-THIS" not in caplog.text
    assert "A private personal reminder" not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.parametrize("setting", ["PASSIVE_MEMORY_RETENTION_DAYS", "CONVERSATION_RETENTION_SECONDS"])
@pytest.mark.parametrize("value", ["-1", "invalid"])
def test_retention_environment_values_fail_clearly(monkeypatch, setting, value):
    from offline_ai_companion.config import _retention_setting
    monkeypatch.setenv(setting, value)
    with pytest.raises(ValueError):
        _retention_setting(setting)


def test_configurable_positive_retention_value(monkeypatch):
    from offline_ai_companion.config import _retention_setting
    monkeypatch.setenv("PASSIVE_MEMORY_RETENTION_DAYS", "30")
    assert _retention_setting("PASSIVE_MEMORY_RETENTION_DAYS") == 30


def test_corrupt_legacy_capture_timestamp_not_destroyed(environment):
    _, facts, _, _ = environment
    repo = PassiveMemoryRepository(facts.database, retention_days=1, clock=lambda: NOW)
    add_observation(repo)
    with facts.database.connect() as db:
        db.execute("UPDATE passive_memories SET captured_at = 'invalid'")
    assert repo.list_memories() == []
    assert repo.purge_expired() == 0
    assert len(repo.list_memories(include_expired=True)) == 1


def test_history_age_and_maximum_turns_share_consistent_lifecycle():
    now = NOW
    manager = ConversationManager(max_turns=2, retention_seconds=60, clock=lambda: now)
    for text in ("One", "Two", "Three"):
        manager.add_turn(text, "Answer")
        now += timedelta(seconds=20)
    assert [t.user for t in manager.get_history()] == ["Two", "Three"]
    now += timedelta(seconds=20)
    assert [t.user for t in manager.get_history()] == ["Three"]
    manager.clear()
    assert manager.get_history() == []
