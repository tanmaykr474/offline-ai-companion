from threading import Event

from .test_always_on_end_to_end import pipeline, scripted_run, wait_until


def test_wake_review_delete_confirmation_and_recall(pipeline, capsys):
    app, facts, _, llm = pipeline
    def barrier(index):
        if index:
            wait_until(lambda: app.passive_worker.queue.unfinished_tasks == 0)
    scripted_run(app, ["I love playing cricket.", "Nova, show my saved memories",
                       "Nova, delete memory number 1", "Nova, yes",
                       "Nova, what sport do I love playing?"], barrier)
    responses = [call.args[0] for call in app.tts.synthesize.call_args_list]
    assert "passive:1" in responses[0] and "unidentified speaker" in responses[0]
    assert "Reply Yes or No" in responses[1]
    assert "Deleted" in responses[2]
    assert "don't have" in responses[3]
    assert app.assistant.passive_memory_repository.list_memories() == []
    assert facts.list_facts() == {}
    assert "cricket" not in capsys.readouterr().out
    llm.generate.assert_not_called()


def test_accepted_background_work_changed_during_bulk_confirmation_is_preserved(pipeline):
    app, facts, processor, _ = pipeline
    facts.set_fact("user.name", "Alice")
    entered, release = Event(), Event()
    original = processor.process
    def delayed(text, captured_at=None):
        entered.set()
        assert release.wait(3)
        return original(text, captured_at=captured_at)
    processor.process = delayed
    app.passive_worker.start()
    try:
        assert app.passive_worker.submit("I was born in Bihar.")
        assert entered.wait(3)
        question = app.assistant.process("Forget everything you remember about me")
        assert "1 records" in question
        release.set()
        assert app.passive_worker.stop(timeout=3)
        assert "reviewed records changed" in app.assistant.process("Yes")
        assert facts.get_fact("user.name") == "Alice"
        assert len(app.assistant.passive_memory_repository.list_memories()) == 1
        assert app.passive_worker.queue.unfinished_tasks == 0
    finally:
        release.set()
        assert app.passive_worker.stop(timeout=3)
