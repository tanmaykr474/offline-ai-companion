from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from offline_ai_companion.core.assistant import Assistant
from offline_ai_companion.memory.database import Database
from offline_ai_companion.memory.repository import MemoryRepository
from offline_ai_companion.memory.passive_repository import PassiveMemoryRepository
from offline_ai_companion.memory.passive_processor import PassiveMemoryProcessor
from offline_ai_companion.memory.confirmation import FactConfirmationManager
from offline_ai_companion.memory.intelligent_extractor import FactProposal
from offline_ai_companion.router.query_router import QueryRouter
from offline_ai_companion.tools.memory_tools import MemoryTools

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)


@pytest.fixture
def environment(tmp_path):
    facts = MemoryRepository(Database(tmp_path / "management.db"))
    llm = Mock(generate=Mock(return_value="A normal chat response."))
    assistant = Assistant(memory_tools=MemoryTools(facts), llm=llm,
                          fact_extractor=Mock(extract=Mock(return_value=None)))
    passive = assistant.passive_memory_repository
    return assistant, facts, passive, llm


def observe(environment, text):
    _, _, passive, llm = environment
    llm.generate.return_value = '{"memories": []}'
    assert PassiveMemoryProcessor(passive, llm).process(text) == 1
    return passive.list_memories()[0].id


def snapshot(facts):
    with facts.database.connect() as db:
        return {table: [tuple(row) for row in db.execute(f"SELECT * FROM {table}")]
                for table in ("facts", "passive_memories", "notes", "tasks", "reminders")}


@pytest.mark.parametrize("query", ["What do you remember about me?", "Show my saved memories.",
                                   "List my preferences.", "What facts have you saved about me?"])
def test_review_is_read_only_bounded_and_typed(environment, query):
    assistant, facts, passive, llm = environment
    facts.set_fact("user.favorite_food", "pizza")
    memory_id = observe(environment, "I love playing cricket.")
    before = snapshot(facts)
    answer = assistant.process(query)
    assert "fact:user.favorite_food" in answer
    assert "Confirmed favorite food: pizza" in answer
    if "facts" not in query:
        assert f"passive:{memory_id}" in answer
        assert "unidentified speaker" in answer
    else:
        assert "passive:" not in answer
    assert len(answer) <= 1400
    assert snapshot(facts) == before
    assert assistant.conversation_manager.turn_count == 0
    llm.generate.assert_not_called()


def test_preferences_filter_and_pagination(environment):
    assistant, facts, passive, _ = environment
    facts.set_fact("user.name", "Alice")
    for index in range(7):
        facts.set_fact(f"user.favorite_topic_{index}", f"value {index}")
    observe(environment, "I was born in Bihar.")
    first = assistant.process("List my preferences")
    second = assistant.process("List my preferences page 2")
    assert first.count("fact:") == 3
    assert second.count("fact:") == 3
    assert "user.name" not in first + second
    assert "Birthplace" not in first + second
    assert "page 2" in first
    assert "topic_0" not in second
    assert "pages start at 1" in assistant.process("Show my saved memories page 0")


def test_stable_passive_id_does_not_address_notes(environment):
    assistant, facts, passive, _ = environment
    note = facts.add_note("Keep this note")
    memory_id = observe(environment, "I love playing cricket.")
    assert note.id == memory_id  # IDs overlap between tables.
    answer = assistant.process(f"Show memory number {memory_id}")
    assert "cricket" in answer and "evidence:" in answer
    before = snapshot(facts)
    assert "Reply Yes or No" in assistant.process(f"Delete memory number {memory_id}")
    assert snapshot(facts) == before
    assert "Deleted" in assistant.process("Yes")
    assert passive.get(memory_id) is None
    assert facts.list_notes()[0].id == note.id
    assert "don't have" in assistant.process("What sport do I love playing?")


@pytest.mark.parametrize("query", ["Forget that I love playing cricket.", "Delete passive:1"])
def test_targeted_observation_deletion(environment, query):
    assistant, facts, passive, _ = environment
    observe(environment, "I love playing cricket.")
    other = observe(environment, "I enjoy listening to music.")
    assert "passive:1" in assistant.process(query)
    assert len(passive.list_memories()) == 2
    assistant.process("confirm deletion")
    assert [m.id for m in passive.list_memories()] == [other]


@pytest.mark.parametrize("query,key,speech", [
    ("Forget my birthplace", "user.birthplace", "I was born in Bihar."),
    ("Remove my favorite food preference", "user.favorite_food", "My favorite food is biryani."),
])
def test_label_deletion_prefers_confirmed_fact_and_explains_preserved_history(environment, query, key, speech):
    assistant, facts, passive, _ = environment
    observe(environment, speech)
    facts.set_fact(key, "confirmed value")
    question = assistant.process(query)
    assert f"fact:{key}" in question
    assert "Historical passive observations remain" in question
    assistant.process("Yes")
    assert facts.get_fact(key) is None
    assert len(passive.list_memories()) == 1


def test_ambiguous_observations_require_typed_target(environment):
    assistant, facts, passive, _ = environment
    observe(environment, "I was born in Bihar.")
    observe(environment, "I was born in Delhi.")
    before = snapshot(facts)
    response = assistant.process("Forget my birthplace")
    assert "Multiple" in response
    assert "passive:1" in response and "passive:2" in response
    assert assistant.memory_management.pending is None
    assistant.process("Yes")
    assert snapshot(facts) == before


@pytest.mark.parametrize("query,key,value,question", [
    ("My favorite food is now pizza.", "user.favorite_food", "pizza", "What is my favorite food?"),
    ("Update my birthplace to Delhi.", "user.birthplace", "Delhi", "Where was I born?"),
    ("Update my favorite programming language to Java", "user.favorite_language", "Java", "What is my favorite programming language?"),
])
def test_correction_preserves_evidence_and_prioritizes_confirmed_fact(environment, query, key, value, question):
    assistant, facts, passive, _ = environment
    observe(environment, "My favorite food is biryani.")
    observe(environment, "I was born in Bihar.")
    facts.set_fact(key, "old value")
    observations = passive.list_memories()
    response = assistant.process(query)
    assert "Historical passive observations" in response
    assert facts.get_fact(key) == "old value"
    assistant.process("Yes")
    assert facts.get_fact(key) == value
    assert value in assistant.process(question)
    assert passive.list_memories() == observations
    assert len([k for k in facts.list_facts() if k == key]) == 1


def test_natural_preference_correction_uses_unique_existing_topic(environment):
    assistant, facts, passive, _ = environment
    observe(environment, "My favorite sport is cricket.")
    before = passive.list_memories()
    assert "fact:user.favorite_sport" in assistant.process("Actually, I prefer football instead of cricket.")
    assistant.process("Yes")
    assert facts.get_fact("user.favorite_sport") == "football"
    assert "football" in assistant.process("What is my favorite sport?")
    assert passive.list_memories() == before


def test_activity_correction_confirms_preference_without_equating_historical_speaker(environment):
    assistant, facts, passive, _ = environment
    observe(environment, "I love playing cricket.")
    before = passive.list_memories()
    response = assistant.process("Actually, I prefer football instead of cricket.")
    assert "fact:user.preferred_activity" in response
    assistant.process("Yes")
    assert "football" in assistant.process("What activities do I prefer?")
    assert passive.list_memories() == before


def test_preference_topic_ambiguity_is_not_guessed(environment):
    assistant, facts, _, _ = environment
    facts.set_fact("user.favorite_sport", "cricket")
    facts.set_fact("user.favorite_game", "cricket")
    before = snapshot(facts)
    assert "Multiple confirmed" in assistant.process("Actually, I prefer football instead of cricket.")
    assistant.process("Yes")
    assert snapshot(facts) == before


@pytest.mark.parametrize("scope,facts_left,passive_left", [
    ("Forget everything you remember about me", 0, 0),
    ("Clear my passive memories", 1, 0),
    ("Delete all saved facts", 0, 1),
])
def test_bulk_scopes_preserve_unrelated_categories(environment, scope, facts_left, passive_left):
    assistant, facts, passive, _ = environment
    facts.set_fact("user.name", "Alice")
    observe(environment, "I love playing cricket.")
    facts.add_note("A note")
    facts.add_task("A task")
    facts.add_reminder("A reminder", NOW)
    assistant.conversation_manager.add_turn("Hello", "Hello Alice")
    before = snapshot(facts)
    response = assistant.process(scope)
    assert "Notes, tasks, reminders and conversation history are preserved" in response
    assert snapshot(facts) == before
    assistant.process("Yes")
    assert len(facts.list_facts()) == facts_left
    assert len(passive.list_memories(include_expired=True)) == passive_left
    after = snapshot(facts)
    for category in ("notes", "tasks", "reminders"):
        assert after[category] == before[category]
    assert assistant.conversation_manager.turn_count == 1


@pytest.mark.parametrize("answer", ["No", "Cancel", "yes but keep some", "go ahead", "yeah"])
def test_cancel_or_ambiguous_confirmation_leaves_all_rows_unchanged(environment, answer):
    assistant, facts, _, _ = environment
    facts.set_fact("user.name", "Alice")
    before = snapshot(facts)
    assistant.process("Delete all saved facts")
    assistant.process(answer)
    assert snapshot(facts) == before
    assert assistant.memory_management.pending is None


def test_unrelated_question_cancels_pending_delete(environment):
    assistant, facts, _, _ = environment
    facts.set_fact("user.name", "Alice")
    assistant.process("Delete all saved facts")
    assert assistant.process("What is my name?") == "Your name is Alice."
    assert "no pending" in assistant.process("Yes")
    assert facts.get_fact("user.name") == "Alice"


def test_repeated_command_reproposes_without_execution(environment):
    assistant, facts, _, _ = environment
    facts.set_fact("user.name", "Alice")
    first = assistant.process("Delete all saved facts")
    assert assistant.process("Delete all saved facts") == first
    assert facts.get_fact("user.name") == "Alice"
    assistant.process("Yes")
    assert "no pending" in assistant.process("Yes")


def test_confirmation_workflows_are_mutually_exclusive(environment):
    assistant, facts, _, _ = environment
    assistant.process("My favorite food is pasta")
    assert assistant.confirmation_manager.pending is not None
    assistant.process("Clear my passive memories")  # Empty scope must still cancel the fact proposal.
    assert assistant.confirmation_manager.pending is None
    assistant.process("Yes")
    assert facts.get_fact("user.favorite_food") is None
    facts.set_fact("user.name", "Alice")
    assistant.process("Delete all saved facts")
    assistant.process("My favorite food is pasta")
    assert assistant.memory_management.pending is None
    assistant.process("Yes")
    assert facts.get_fact("user.name") == "Alice"
    assert facts.get_fact("user.favorite_food") == "pasta"


@pytest.mark.parametrize("kind", ["management", "fact"])
def test_pending_operation_expires_at_exact_boundary(environment, kind):
    assistant, facts, _, _ = environment
    now = NOW
    assistant.memory_management.clock = lambda: now
    assistant.confirmation_manager.clock = lambda: now
    if kind == "management":
        facts.set_fact("user.name", "Alice")
        assistant.process("Delete all saved facts")
    else:
        assistant.process("My favorite food is pasta")
    before = snapshot(facts)
    now += timedelta(seconds=120)
    assert "expired" in assistant.process("Yes")
    assert snapshot(facts) == before


def test_restart_does_not_restore_pending_delete_or_correction(environment):
    assistant, facts, _, llm = environment
    facts.set_fact("user.name", "Alice")
    assistant.process("Delete all saved facts")
    restarted = Assistant(memory_tools=MemoryTools(MemoryRepository(Database(facts.database.path))), llm=llm)
    assert "no pending" in restarted.process("Yes")
    assert restarted.process("What is my name?") == "Your name is Alice."


@pytest.mark.parametrize("change", ["targeted", "bulk", "correction"])
def test_changed_records_cancel_reviewed_write(environment, change):
    assistant, facts, _, _ = environment
    facts.set_fact("user.name", "Alice")
    if change == "targeted":
        assistant.process("Delete fact:user.name")
        facts.set_fact("user.name", "Bob")
    elif change == "bulk":
        assistant.process("Delete all saved facts")
        facts.set_fact("user.city", "Delhi")
    else:
        assistant.process("Update my name to Bob")
        facts.set_fact("user.name", "Carol")
    before = snapshot(facts)
    assert "reviewed records changed" in assistant.process("Yes")
    assert snapshot(facts) == before


def test_transaction_rollback_restores_all_categories(environment):
    assistant, facts, passive, _ = environment
    facts.set_fact("user.name", "Alice")
    observe(environment, "I love playing cricket.")
    with facts.database.connect() as db:
        db.execute("CREATE TRIGGER refuse_delete BEFORE DELETE ON passive_memories BEGIN SELECT RAISE(ABORT, 'private database failure'); END")
    before = snapshot(facts)
    assistant.process("Forget everything you remember about me")
    assert "rolled back" in assistant.process("Yes")
    assert snapshot(facts) == before


def test_expired_rows_hidden_from_review_but_explicit_bulk_clear_can_remove(environment):
    assistant, facts, _, _ = environment
    passive = PassiveMemoryRepository(facts.database, retention_days=1, clock=lambda: NOW)
    passive.add("fact", "speaker", "Birthplace is Bihar", "I was born in Bihar.", captured_at=NOW - timedelta(days=2))
    assistant.passive_memory_repository = passive
    assistant.memory_management.passive = passive
    assert "Bihar" not in assistant.process("Show my saved memories")
    assert "No visible" in assistant.process("Show memory number 1")
    assert "including expired" in assistant.process("Clear my passive memories")
    assistant.process("Yes")
    assert passive.list_memories(include_expired=True) == []


def test_credential_values_are_never_reviewed_or_spoken(environment):
    assistant, facts, passive, _ = environment
    facts.set_fact("user.name", "Alice")
    memory_id = observe(environment, "I love playing cricket.")
    with facts.database.connect() as db:
        db.execute("INSERT INTO facts (key, value) VALUES ('user.password', 'dont-speak-THIS')")
        db.execute("UPDATE passive_memories SET evidence = 'password: dont-speak-THIS' WHERE id = ?", (memory_id,))
    assert "dont-speak-THIS" not in assistant.process("Show my saved memories")
    assert "dont-speak-THIS" not in assistant.process("Show fact:user.password")
    assert "dont-speak-THIS" not in assistant.process(f"Show memory number {memory_id}")
    assert "dont-speak-THIS" not in assistant.process(f"Delete memory number {memory_id}")
    assistant.process("Yes")
    assert passive.get(memory_id) is None


def test_typed_nonexistent_id_cannot_delete_another_category(environment):
    assistant, facts, passive, _ = environment
    facts.add_note("Keep this note")
    assert "No matching" in assistant.process("Delete memory number 1")
    assistant.process("Yes")
    assert len(facts.list_notes()) == 1


def test_command_router_detects_management_without_using_llm():
    router = QueryRouter()
    for text in ("Show my saved memories", "Delete memory number 5", "Update my birthplace to Delhi"):
        assert router.route(text).intent == "memory_management"


@pytest.mark.parametrize("action,answer", [("Delete all saved facts", "yes update"),
                                           ("Update my name to Bob", "yes delete")])
def test_confirmation_cannot_name_a_different_action(environment, action, answer):
    assistant, facts, _, _ = environment
    facts.set_fact("user.name", "Alice")
    before = snapshot(facts)
    assistant.process(action)
    assert "different action" in assistant.process(answer)
    assert snapshot(facts) == before


def test_confirmed_preference_topic_wins_over_other_passive_topic(environment):
    assistant, facts, _, _ = environment
    facts.set_fact("user.favorite_sport", "cricket")
    observe(environment, "My favorite game is cricket.")
    response = assistant.process("Actually, I prefer football instead of cricket")
    assert "fact:user.favorite_sport" in response
    assistant.process("Yes")
    assert facts.get_fact("user.favorite_sport") == "football"
    assert facts.get_fact("user.favorite_game") is None


def test_management_change_survives_sqlite_restart(environment):
    assistant, facts, _, llm = environment
    facts.set_fact("user.favorite_food", "pasta")
    assistant.process("My favorite food is now pizza")
    assistant.process("Yes")
    restarted = Assistant(memory_tools=MemoryTools(MemoryRepository(Database(facts.database.path))), llm=llm)
    assert restarted.process("What is my favorite food?") == "Your favorite food is pizza."
    restarted.process("Forget my favorite food")
    restarted.process("Yes")
    assert MemoryRepository(Database(facts.database.path)).get_fact("user.favorite_food") is None


def test_expired_fact_confirmation_does_not_swallow_unrelated_question(environment):
    assistant, facts, _, _ = environment
    now = NOW
    assistant.confirmation_manager.clock = lambda: now
    facts.set_fact("user.name", "Alice")
    assistant.process("My favorite food is pasta")
    now += timedelta(seconds=120)
    assert assistant.process("What is my name?") == "Your name is Alice."
    assert facts.get_fact("user.favorite_food") is None


def test_secret_query_cancels_pending_destructive_operation(environment):
    assistant, facts, _, _ = environment
    facts.set_fact("user.name", "Alice")
    assistant.process("Delete all saved facts")
    assert "can't store" in assistant.process("password: never-save-THIS")
    assistant.process("Yes")
    assert facts.get_fact("user.name") == "Alice"


def test_targeted_delete_does_not_claim_to_delete_historical_observation(environment):
    assistant, facts, _, _ = environment
    facts.set_fact("user.favorite_food", "pizza")
    observe(environment, "My favorite food is biryani.")
    assistant.process("Forget my favorite food")
    assistant.process("Yes")
    assert "biryani" in assistant.process("What is my favorite food?")


def test_named_other_speaker_is_not_resolved_as_my_personal_memory(environment):
    assistant, _, passive, _ = environment
    passive.add("fact", "Alice", "Birthplace is Bihar", "I was born in Bihar.")
    assert "No matching" in assistant.process("Forget my birthplace")
    assert "Alice" in assistant.process("Show memory number 1")
    assert len(passive.list_memories()) == 1


def test_explicit_id_can_remove_retained_expired_observation(environment):
    assistant, facts, _, _ = environment
    repo = PassiveMemoryRepository(facts.database, retention_days=1, clock=lambda: NOW)
    repo.add("fact", "speaker", "Birthplace is Bihar", "I was born in Bihar.", captured_at=NOW - timedelta(days=2))
    assistant.memory_management.passive = repo
    assert "passive:1" in assistant.process("Delete memory number 1")
    assistant.process("Yes")
    assert repo.get(1, include_expired=True) is None


def test_repository_fact_delete_and_clear_apis_preserve_notes(environment):
    _, facts, _, _ = environment
    facts.set_fact("user.name", "Alice")
    facts.set_fact("user.city", "Delhi")
    facts.add_note("Keep this note")
    assert facts.delete_fact("user.name")
    assert not facts.delete_fact("user.name")
    assert facts.clear_facts() == 1
    assert facts.clear_facts() == 0
    assert len(facts.list_notes()) == 1


def test_mutations_across_different_databases_fail_without_changes(environment, tmp_path):
    assistant, facts, _, _ = environment
    other = PassiveMemoryRepository(Database(tmp_path / "other.db"))
    other.add("fact", "speaker", "Birthplace is Bihar", "I was born in Bihar.")
    assistant.memory_management.passive = other
    facts.set_fact("user.name", "Alice")
    assert "different databases" in assistant.process("Forget everything you remember about me")
    assistant.process("Yes")
    assert facts.get_fact("user.name") == "Alice"
    assert len(other.list_memories()) == 1


def test_confirmation_expiring_after_transaction_lock_is_not_executed(environment):
    assistant, facts, _, _ = environment
    facts.set_fact("user.name", "Alice")
    times = iter([NOW, NOW, NOW + timedelta(seconds=120)])
    assistant.memory_management.clock = lambda: next(times)
    assistant.process("Delete all saved facts")
    assert "expired" in assistant.process("Yes")
    assert facts.get_fact("user.name") == "Alice"


def test_correction_failure_rolls_back_existing_fact(environment):
    assistant, facts, _, _ = environment
    facts.set_fact("user.favorite_food", "pasta")
    with facts.database.connect() as db:
        db.execute("CREATE TRIGGER refuse_update BEFORE UPDATE ON facts BEGIN SELECT RAISE(ABORT, 'private failure'); END")
    before = snapshot(facts)
    assistant.process("My favorite food is now pizza")
    assert "rolled back" in assistant.process("Yes")
    assert snapshot(facts) == before


def test_optional_wake_prefix_on_management_confirmation(environment):
    assistant, facts, _, _ = environment
    facts.set_fact("user.name", "Alice")
    assistant.process("Nova, delete all saved facts")
    assert "Deleted" in assistant.process("Nova, yes")
    assert facts.list_facts() == {}
