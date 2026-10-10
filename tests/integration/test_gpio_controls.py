"""Real voice/memory/privacy orchestration with exclusively mocked GPIO."""
import logging
import sys
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from .test_always_on_end_to_end import pipeline, module
from offline_ai_companion.core import hardware as hw
from offline_ai_companion.core import service_runtime as service
from offline_ai_companion.core.privacy import SoftwareMute
from offline_ai_companion.core.state import AssistantState as S


@pytest.fixture
def controls(pipeline):
    app, repository, processor, llm = pipeline
    now = [0.0]
    backend = hw.MockBackend()
    controller = hw.HardwareController(app, hw.HardwareConfig(backend="mock"), lambda: backend, lambda: now[0])
    app._hardware = controller
    yield app, controller, backend, now, repository
    controller.close()


def authorize(controller, backend, now):
    backend.muted = True
    controller.poll_once()
    now[0] += .2
    controller.poll_once()
    backend.muted = False
    controller.poll_once()
    now[0] += .2
    controller.poll_once()


@pytest.mark.parametrize("state,rgb", [(S.LISTENING, (False, True, False)),
    (S.PROCESSING, (False, False, True)), (S.SPEAKING, (False, False, True)),
    (S.IDLE, (False, False, False)), (S.INTERRUPTED, (False, False, False))])
def test_led_follows_existing_state_machine(controls, state, rgb):
    app, controller, backend, now, _ = controls
    authorize(controller, backend, now)
    app.set_state(state)
    assert backend.rgb == rgb


@pytest.mark.parametrize("state", [S.LISTENING, S.PROCESSING, S.SPEAKING, S.IDLE, S.INTERRUPTED])
def test_mute_has_priority_over_led_states(controls, state):
    app, _, backend, _, _ = controls
    app.set_state(state)
    assert app.privacy.muted
    assert backend.rgb == (True, False, False)


def test_shutdown_off_is_latched_and_close_is_idempotent(controls):
    app, controller, backend, now, _ = controls
    authorize(controller, backend, now)
    app.set_state(S.SHUTTING_DOWN)
    assert backend.rgb == (False, False, False)
    app.set_state(S.IDLE)
    controller.poll_once()
    assert backend.rgb == (False, False, False)
    controller.close()
    controller.close()
    assert backend.closed and app.privacy.muted


@pytest.mark.parametrize("position", [True, False])
def test_startup_muted_regardless_of_switch_position(pipeline, position):
    app = pipeline[0]
    backend = hw.MockBackend(position)
    now = [0.0]
    controller = hw.HardwareController(app, hw.HardwareConfig(backend="mock"), lambda: backend, lambda: now[0])
    app._hardware = controller
    now[0] = 1
    controller.poll_once()
    app.set_muted(False)
    assert app.privacy.muted
    controller.close()


def test_switch_release_is_debounced_and_new_mute_is_immediate(controls):
    app, controller, backend, now, _ = controls
    now[0] = .2
    controller.poll_once()  # Establish stable muted position.
    backend.muted = False
    controller.poll_once()
    now[0] += .02
    controller.poll_once()
    assert app.privacy.muted
    backend.muted = True
    controller.poll_once()
    backend.muted = False
    now[0] += .02
    controller.poll_once()
    now[0] += .2
    controller.poll_once()
    assert not app.privacy.muted
    backend.muted = True
    controller.poll_once()
    assert app.privacy.muted
    app.toggle_mute()
    assert app.privacy.muted


def test_switch_does_not_override_later_software_mute(controls):
    app, controller, backend, now, _ = controls
    authorize(controller, backend, now)
    app.set_muted(True)
    now[0] += 1
    controller.poll_once()
    assert app.privacy.muted
    app.toggle_mute()
    assert not app.privacy.muted


def test_physical_mute_invalidates_recording_and_blocks_new_memory(controls):
    app, controller, backend, now, repository = controls
    authorize(controller, backend, now)
    generation, cancellation = app.privacy.snapshot()
    backend.muted = True
    controller.poll_once()
    assert cancellation.is_set()
    app.process_recording(app.input_path, generation=generation)
    app.stt.transcribe.assert_not_called()
    assert repository.list_tasks() == []
    with app.privacy.guard(generation) as accepted:
        assert not accepted
    app.passive_worker.privacy = app.privacy
    app.passive_worker.start()
    assert not app.passive_worker.submit("I love playing cricket.")


@pytest.mark.parametrize("fault", ["read", "led"])
def test_gpio_error_latches_mute_and_never_auto_recovers(controls, fault):
    app, controller, backend, now, _ = controls
    authorize(controller, backend, now)
    backend.error = True
    if fault == "read":
        controller.poll_once()
    else:
        app.set_state(S.LISTENING)
    assert controller.faulted and app.privacy.muted and backend.closed
    backend.error = False
    backend.muted = False
    now[0] += 1
    controller.poll_once()
    app.set_muted(False)
    assert app.privacy.muted


def test_initialization_failure_has_no_private_exception_logging(pipeline, caplog):
    app = pipeline[0]
    def unavailable():
        raise OSError("private credential in driver error")
    with caplog.at_level(logging.ERROR):
        controller = hw.HardwareController(app, hw.HardwareConfig(backend="mock"), unavailable)
    assert controller.faulted and app.privacy.muted
    assert isinstance(controller.backend, hw.NoopBackend)
    assert "credential" not in caplog.text
    controller.close()


def test_mock_backend_poll_thread_stops_cleanly(controls):
    _, controller, backend, _, _ = controls
    controller.start()
    controller.close()
    assert not controller.thread.is_alive()
    assert backend.closed


def test_task_and_interruption_preserve_committed_records(controls):
    app, controller, backend, now, repository = controls
    authorize(controller, backend, now)
    app.experimental_interruption = True
    app.handle_transcript("Nova, add a task to finish my project")
    assert len(repository.list_tasks()) == 1
    token = app.response_control.begin()
    backend.muted = True
    controller.poll_once()
    assert token.cancel.is_set()
    assert len(repository.list_tasks()) == 1
    app.response_control.finish(token)


def test_physical_mute_interrupts_reminder_without_duplicate_completion(controls):
    from offline_ai_companion.scheduler.reminder_scheduler import ReminderScheduler
    from offline_ai_companion.core.cancellation import check_cancel
    app, controller, backend, now, repository = controls
    authorize(controller, backend, now)
    app.experimental_interruption = True
    moment = datetime(2026, 10, 10, tzinfo=timezone.utc)
    reminder = repository.add_reminder("take a break", moment - timedelta(minutes=1))
    def mute_playback(*args, **kwargs):
        backend.muted = True
        controller.poll_once()
        check_cancel(kwargs["cancel_event"])
    app.player.play.side_effect = mute_playback
    scheduler = ReminderScheduler(repository, lambda item: app.speak(item.message), clock=lambda: moment)
    assert scheduler.check_due() == 0
    assert not repository.list_reminders()[0].is_completed
    app.player.play.side_effect = None
    authorize(controller, backend, now)
    scheduler.clock = lambda: moment + timedelta(seconds=60)
    assert scheduler.check_due() == 1
    assert scheduler.check_due() == 0
    assert repository.list_reminders()[0].id == reminder.id


def test_accepted_background_work_drains_after_physical_mute(controls):
    app, controller, backend, now, _ = controls
    authorize(controller, backend, now)
    worker = app.passive_worker
    worker.privacy = app.privacy
    original = worker.processor.process
    entered, release = Event(), Event()
    def blocked(text, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(text, **kwargs)
    worker.processor.process = blocked
    worker.start()
    try:
        assert worker.submit("I love playing cricket.")
        assert entered.wait(3)
        backend.muted = True
        controller.poll_once()
        assert not worker.submit("I enjoy listening to music.")
        release.set()
        assert worker.stop(timeout=3)
        saved = app.assistant.passive_memory_repository.list_memories()
        assert len(saved) == 1 and "cricket" in saved[0].content
    finally:
        release.set()


def test_shutdown_run_cleans_audio_and_hardware_without_terminal(pipeline, monkeypatch):
    app = pipeline[0]
    app._temporary_audio = Mock()
    app.recorder.record_utterance.side_effect = KeyboardInterrupt
    # Authorized just before entering run to exercise its real shutdown finally.
    monkeypatch.setattr(service.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service.platform, "machine", lambda: "aarch64")
    original = app.run
    backend = hw.MockBackend()
    def run():
        controller = app._hardware
        controller.candidate_since -= 1
        controller.poll_once()
        backend.muted = False
        controller.poll_once()
        controller.candidate_since -= 1
        controller.poll_once()
        original()
    app.run = run
    assert service.run_voice(lambda: app, {"NOVA_HEADLESS": "true", "NOVA_GPIO_BACKEND": "lgpio"}, lambda: backend, fake_signals()) == 0
    assert backend.closed and app._closed and app.stop_event.is_set()
    app._temporary_audio.close.assert_called()
    assert app.state == S.IDLE


@pytest.mark.parametrize("kwargs", [{"red": 27}, {"switch": 22}, {"blue": 0}, {"green": 28},
    {"red": True}, {"chip": -1}, {"chip": 64}, {"debounce": float("nan")},
    {"debounce": .01}, {"debounce": 2}, {"poll_interval": float("inf")}, {"poll_interval": 0}, {"backend": "pigpio"}])
def test_invalid_pin_or_timing_configuration(kwargs):
    with pytest.raises(hw.HardwareConfigurationError):
        hw.HardwareConfig(**kwargs)


@pytest.mark.parametrize("environment", [{"NOVA_LED_RED_BCM": "private-value"},
    {"NOVA_LED_ACTIVE_HIGH": "yes"}, {"NOVA_GPIO_CHIP": "secret"}, {"NOVA_SWITCH_MUTED_HIGH": "unknown"}])
def test_environment_failures_are_sanitized(environment):
    with pytest.raises(hw.HardwareConfigurationError) as error:
        hw.HardwareConfig.from_env(environment)
    assert not any(value in str(error.value) for value in environment.values())


def test_real_gpio_is_never_opened_on_windows(monkeypatch):
    monkeypatch.setattr(hw.platform, "system", lambda: "Windows")
    dependency_check = Mock()
    monkeypatch.setattr(hw, "validate_gpio_dependencies", dependency_check)
    with pytest.raises(hw.HardwareConfigurationError, match="Linux ARM64"):
        hw.LGPIOBackend(hw.HardwareConfig(backend="lgpio"))
    dependency_check.assert_not_called()


@pytest.mark.parametrize("active_high,muted_high", [(True, True), (False, True), (True, False), (False, False)])
def test_lgpio_uses_explicit_factory_chip_polarity_and_cleans_up(monkeypatch, active_high, muted_high):
    monkeypatch.setattr(hw.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hw.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(hw, "validate_gpio_dependencies", lambda: True)
    factory = Mock()
    factory_type = Mock(return_value=factory)
    input_device = Mock(pin=SimpleNamespace(state=muted_high))
    input_type = Mock(return_value=input_device)
    outputs = [Mock(), Mock(), Mock()]
    output_type = Mock(side_effect=outputs)
    monkeypatch.setitem(sys.modules, "gpiozero", SimpleNamespace(DigitalInputDevice=input_type, DigitalOutputDevice=output_type))
    monkeypatch.setitem(sys.modules, "gpiozero.pins.lgpio", SimpleNamespace(LGPIOFactory=factory_type))
    config = hw.HardwareConfig(backend="lgpio", chip=4, active_high=active_high, muted_high=muted_high)
    backend = hw.LGPIOBackend(config)
    factory_type.assert_called_once_with(chip=4)
    assert input_type.call_args.kwargs["pull_up"] is muted_high
    assert all(call.kwargs["active_high"] is active_high and call.kwargs["initial_value"] is False for call in output_type.call_args_list)
    assert backend.read_muted()
    input_device.pin.state = not muted_high
    assert not backend.read_muted()
    backend.set_rgb(True, False, False)
    assert outputs[0].value is True and outputs[1].value is False
    backend.close()
    backend.close()
    factory.close.assert_called_once()
    for device in [input_device] + outputs:
        device.close.assert_called_once()


def fake_signals():
    return SimpleNamespace(SIGTERM=15, getsignal=Mock(return_value="old-handler"), signal=Mock())


def test_sigterm_uses_cleanup_path_and_repeated_signals_do_not_abort_drain(pipeline):
    app = pipeline[0]
    signals = fake_signals()
    with service.termination_handler(app, signals):
        callback = signals.signal.call_args.args[1]
        with pytest.raises(KeyboardInterrupt):
            callback(15, None)
        assert app.stop_event.is_set()
        callback(15, None)
    signals.signal.assert_called_with(15, "old-handler")


def test_headless_runtime_needs_no_keyboard_and_closes_gpio(pipeline, monkeypatch):
    app = pipeline[0]
    monkeypatch.setattr(service.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service.platform, "machine", lambda: "aarch64")
    keys = Mock(side_effect=AssertionError("Headless mode must not instantiate console controls"))
    monkeypatch.setattr(service, "PosixMuteConsole", keys)
    backend = hw.MockBackend()
    signals = fake_signals()
    def run():
        assert app.privacy.muted and app._hardware is not None
        assert app._hardware.thread.is_alive()
        signals.signal.call_args.args[1](15, None)
    app.run = Mock(side_effect=run)
    assert service.run_voice(lambda: app, {"NOVA_HEADLESS": "true", "NOVA_GPIO_BACKEND": "lgpio"}, lambda: backend, signals) == 0
    assert backend.closed and app.privacy.muted
    keys.assert_not_called()


@pytest.mark.parametrize("backend", ["none", "mock"])
def test_headless_rejects_missing_real_backend_before_app_creation(monkeypatch, backend):
    monkeypatch.setattr(service.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service.platform, "machine", lambda: "aarch64")
    factory = Mock()
    assert service.run_voice(factory, {"NOVA_HEADLESS": "true", "NOVA_GPIO_BACKEND": backend}) == 78
    factory.assert_not_called()


def test_headless_failed_gpio_prevents_voice_loop(pipeline, monkeypatch):
    app = pipeline[0]
    monkeypatch.setattr(service.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service.platform, "machine", lambda: "arm64")
    app.run = Mock()
    assert service.run_voice(lambda: app, {"NOVA_HEADLESS": "true", "NOVA_GPIO_BACKEND": "lgpio"}, hw.NoopBackend, fake_signals()) == 78
    app.run.assert_not_called()
    assert app.privacy.muted


def test_gate_physical_override_cannot_be_bypassed_and_old_tokens_stay_cancelled():
    gate = SoftwareMute()
    generation, token = gate.snapshot()
    gate.set_physical_muted(True)
    gate.set_muted(False)
    assert gate.muted and token.is_set()
    with gate.guard(generation) as accepted:
        assert not accepted
    gate.set_muted(True)
    gate.set_physical_muted(False)
    assert gate.muted


@pytest.mark.parametrize("version,missing,expected", [("2.0.1", False, True), ("1.6.2", False, False),
    ("3.0.0", False, False), ("2.0.1", True, False)])
def test_gpio_dependency_version_and_api_validation_never_opens_chip(monkeypatch, version, missing, expected):
    import importlib.metadata
    monkeypatch.setattr(importlib.metadata, "version", lambda _: version)
    factory, input_type, output_type = Mock(), Mock(), Mock()
    monkeypatch.setitem(sys.modules, "gpiozero", SimpleNamespace(DigitalInputDevice=input_type, DigitalOutputDevice=output_type))
    monkeypatch.setitem(sys.modules, "gpiozero.pins.lgpio", SimpleNamespace(LGPIOFactory=factory))
    api = {name: Mock() for name in ("gpiochip_open", "gpio_read", "gpio_claim_input", "gpio_claim_output")}
    if missing:
        api.pop("gpio_read")
    monkeypatch.setitem(sys.modules, "lgpio", SimpleNamespace(**api))
    assert hw.validate_gpio_dependencies() is expected
    factory.assert_not_called()
    for operation in api.values():
        operation.assert_not_called()


def test_partial_gpio_initialization_closes_previously_acquired_devices(monkeypatch):
    monkeypatch.setattr(hw.platform, "system", lambda: "Linux")
    monkeypatch.setattr(hw.platform, "machine", lambda: "aarch64")
    monkeypatch.setattr(hw, "validate_gpio_dependencies", lambda: True)
    factory, input_device, output = Mock(), Mock(), Mock()
    monkeypatch.setitem(sys.modules, "gpiozero", SimpleNamespace(DigitalInputDevice=Mock(return_value=input_device),
        DigitalOutputDevice=Mock(side_effect=[output, OSError("pin busy")])) )
    monkeypatch.setitem(sys.modules, "gpiozero.pins.lgpio", SimpleNamespace(LGPIOFactory=Mock(return_value=factory)))
    with pytest.raises(OSError):
        hw.LGPIOBackend(hw.HardwareConfig(backend="lgpio"))
    input_device.close.assert_called_once()
    output.off.assert_called_once()
    output.close.assert_called_once()
    factory.close.assert_called_once()


def test_headless_runtime_failure_is_sanitized_and_releases_gpio(pipeline, monkeypatch, caplog):
    app = pipeline[0]
    monkeypatch.setattr(service.platform, "system", lambda: "Linux")
    monkeypatch.setattr(service.platform, "machine", lambda: "aarch64")
    backend = hw.MockBackend()
    app.run = Mock(side_effect=RuntimeError("private transcript in unexpected exception"))
    with caplog.at_level(logging.ERROR):
        assert service.run_voice(lambda: app, {"NOVA_HEADLESS": "true", "NOVA_GPIO_BACKEND": "lgpio"}, lambda: backend, fake_signals()) == 1
    assert backend.closed and app.privacy.muted
    assert "RuntimeError" in caplog.text and "private transcript" not in caplog.text
