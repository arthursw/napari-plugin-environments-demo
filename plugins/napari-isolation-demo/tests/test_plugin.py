from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from napari import plugins as napari_plugins
from napari.utils import notifications
from napari_isolation_demo import IsolationDemoWidget
from npe2 import PluginManifest
from qtpy.QtWidgets import QSizePolicy

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / 'src' / 'napari_isolation_demo'


class FakeContext:
    cancel_requested = False

    def __init__(self) -> None:
        self.messages: list[str] = []

    def update(
        self,
        message: str,
        *,
        current: int | None = None,
        maximum: int | None = None,
    ) -> None:
        self.messages.append(message)


class FakeTask:
    def __init__(self) -> None:
        self.state = SimpleNamespace(value='running')
        self.error = None
        self._done_callbacks = []
        self.cancel_calls = 0

    def cancel(self, _reason: str) -> None:
        self.cancel_calls += 1

    def add_progress_callback(self, _callback) -> None:
        pass

    def add_done_callback(self, callback) -> None:
        self._done_callbacks.append(callback)

    def finish(self, state: str) -> None:
        self.state = SimpleNamespace(value=state)
        for callback in self._done_callbacks:
            callback(self)

    def result(self):
        raise AssertionError('result() must not be called for a canceled task')


def _worker_module():
    path = PACKAGE / 'worker' / 'napari_isolation_worker.py'
    spec = importlib.util.spec_from_file_location(
        'napari_isolation_worker', path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_declares_two_environments_with_one_worker_project() -> None:
    manifest = PluginManifest.from_file(PACKAGE / 'napari.yaml')

    assert manifest.contributions.worker_package == 'worker'
    assert [
        str(item.id) for item in manifest.contributions.environments or ()
    ] == [
        'napari-isolation-demo.numpy1',
        'napari-isolation-demo.numpy2',
    ]
    worker_commands = [
        command
        for command in manifest.contributions.commands or ()
        if command.environment is not None
    ]
    assert all(command.accepts_worker_context for command in worker_commands)
    assert manifest.contributions.widgets[0].display_name == 'Threshold'
    manifest.validate_environment_resources()


def test_threshold_returns_supported_nested_values() -> None:
    worker = _worker_module()
    context = FakeContext()
    image = np.array([[0.0, 0.75], [1.0, 0.25]], dtype=np.float32)

    result = worker.threshold(
        image, {'threshold': 0.5}, napari_context=context
    )

    assert result is not None
    np.testing.assert_array_equal(
        result['labels'], np.array([[0, 1], [1, 0]], dtype=np.uint8)
    )
    assert result['worker_pid'] == os.getpid()
    assert result['metadata'] == {
        'shape': (2, 2),
        'threshold': 0.5,
        'values': [0, 1],
    }
    assert context.messages == ['Thresholding image', 'Returning labels']


def test_slow_worker_honors_cancellation() -> None:
    worker = _worker_module()
    context = FakeContext()
    context.cancel_requested = True

    assert worker.slow_operation(10, 0.1, napari_context=context) is None
    assert context.messages == ['Running cancellable operation']


def test_widget_presents_cancellation_without_error(
    qtbot, monkeypatch
) -> None:
    viewer = SimpleNamespace(
        layers=SimpleNamespace(
            selection=SimpleNamespace(
                active=SimpleNamespace(data=np.zeros((4, 4)))
            )
        ),
        add_labels=lambda *args, **kwargs: None,
    )
    task = FakeTask()
    errors: list[str] = []
    monkeypatch.setattr(
        napari_plugins,
        'execute_worker_command',
        lambda *args, **kwargs: task,
        raising=False,
    )
    monkeypatch.setattr(notifications, 'show_error', errors.append)
    widget = IsolationDemoWidget(viewer)
    qtbot.addWidget(widget)

    widget.run()
    widget.cancel()
    task.finish('canceled')

    assert task.cancel_calls == 1
    assert widget.status.text() == 'Operation canceled.'
    assert widget.run_button.isEnabled()
    assert not widget.cancel_button.isEnabled()
    assert errors == []


def test_widget_selects_two_environments_from_its_own_plugin(
    qtbot, monkeypatch
) -> None:
    viewer = SimpleNamespace(
        layers=SimpleNamespace(
            selection=SimpleNamespace(
                active=SimpleNamespace(data=np.zeros((4, 4)))
            )
        ),
        add_labels=lambda *args, **kwargs: None,
    )
    tasks = [FakeTask(), FakeTask()]
    calls: list[str] = []

    def execute(command_id, *args, **kwargs):
        calls.append(command_id)
        return tasks[len(calls) - 1]

    monkeypatch.setattr(
        napari_plugins,
        'execute_worker_command',
        execute,
        raising=False,
    )
    widget = IsolationDemoWidget(viewer)
    qtbot.addWidget(widget)

    widget.run()
    tasks[0].finish('canceled')
    widget.environment.setCurrentIndex(1)
    widget.run()

    assert calls == [
        'napari-isolation-demo.threshold_numpy1',
        'napari-isolation-demo.threshold_numpy2',
    ]


def test_long_failure_does_not_force_a_wide_dock(qtbot, monkeypatch) -> None:
    viewer = SimpleNamespace(
        layers=SimpleNamespace(
            selection=SimpleNamespace(
                active=SimpleNamespace(data=np.zeros((4, 4)))
            )
        ),
        add_labels=lambda *args, **kwargs: None,
    )
    task = FakeTask()
    monkeypatch.setattr(
        napari_plugins,
        'execute_worker_command',
        lambda *args, **kwargs: task,
        raising=False,
    )
    errors: list[str] = []
    monkeypatch.setattr(notifications, 'show_error', errors.append)
    widget = IsolationDemoWidget(viewer)
    qtbot.addWidget(widget)

    widget.run()
    task.error = RuntimeError('/very-long-path' * 100)
    task.finish('failed')

    assert widget.status.wordWrap()
    assert widget.status.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored
    assert len(widget.status.text()) < 180
    assert errors == []


def test_widget_explains_unavailable_startup_environment(
    qtbot, monkeypatch
) -> None:
    from napari.plugins.environments import (
        PluginEnvironmentUnavailableError,
    )

    viewer = SimpleNamespace(
        layers=SimpleNamespace(
            selection=SimpleNamespace(
                active=SimpleNamespace(data=np.zeros((4, 4)))
            )
        ),
        add_labels=lambda *args, **kwargs: None,
    )
    task = FakeTask()
    monkeypatch.setattr(
        napari_plugins,
        'execute_worker_command',
        lambda *args, **kwargs: task,
        raising=False,
    )
    monkeypatch.setattr(notifications, 'show_error', lambda message: None)
    widget = IsolationDemoWidget(viewer)
    qtbot.addWidget(widget)

    widget.run()
    task.error = PluginEnvironmentUnavailableError(
        'Environment setup was skipped. Restart napari to retry setup.'
    )
    task.finish('failed')

    assert widget.status.text() == (
        'Environment unavailable: Environment setup was skipped. Restart '
        'napari to retry setup.'
    )
    assert widget.run_button.isEnabled()
