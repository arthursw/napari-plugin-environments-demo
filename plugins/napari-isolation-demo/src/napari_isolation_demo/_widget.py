from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from qtpy.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    import napari


class IsolationDemoWidget(QWidget):
    """Run one plugin command in two incompatible managed environments."""

    COMMANDS = (
        (
            'NumPy 1.26',
            'napari-isolation-demo.threshold_numpy1',
        ),
        (
            'NumPy 2.2',
            'napari-isolation-demo.threshold_numpy2',
        ),
    )

    def __init__(self, napari_viewer: napari.Viewer) -> None:
        super().__init__()
        self.viewer = napari_viewer
        self._task: Any = None

        self.environment = QComboBox()
        for label, command in self.COMMANDS:
            self.environment.addItem(label, command)

        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(-1_000_000, 1_000_000)
        self.threshold.setDecimals(4)
        self.threshold.setValue(0.5)

        form = QFormLayout()
        form.addRow('Plugin environment:', self.environment)
        form.addRow('Threshold:', self.threshold)

        self.run_button = QPushButton('Run threshold')
        self.cancel_button = QPushButton('Cancel')
        self.cancel_button.setEnabled(False)
        buttons = QHBoxLayout()
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()

        self.status = QLabel('Ready')
        self.status.setWordWrap(True)
        self.status.setMinimumWidth(0)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addStretch()
        self.setMinimumWidth(320)

        self.run_button.clicked.connect(self.run)
        self.cancel_button.clicked.connect(self.cancel)

    def run(self) -> None:
        layer = self.viewer.layers.selection.active
        if layer is None:
            self.status.setText('Select an image layer first.')
            return

        from napari.plugins import execute_worker_command

        self._set_busy(True)
        self.status.setText('Starting plugin worker…')
        try:
            task = execute_worker_command(
                str(self.environment.currentData()),
                np.asarray(layer.data),
                {'threshold': float(self.threshold.value())},
            )
        except Exception as error:  # noqa: BLE001 - Qt error boundary
            self._show_error(error, notify=True)
            return
        self._task = task
        task.add_progress_callback(self._on_progress)
        task.add_done_callback(self._on_done)

    def cancel(self) -> None:
        if self._task is not None:
            self.cancel_button.setEnabled(False)
            self.status.setText('Canceling…')
            self._task.cancel('Canceled from the isolation demo widget')

    def _on_progress(self, progress: Any) -> None:
        self.status.setText(progress.message)
        if progress.current is None or progress.total is None:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, progress.total)
            self.progress.setValue(progress.current)

    def _on_done(self, task: Any) -> None:
        try:
            state = task.state.value
            if state == 'completed':
                result = task.result()
                if result is None:
                    self.status.setText('Operation canceled.')
                    return
                version = result['numpy_version']
                self.viewer.add_labels(
                    np.asarray(result['labels']),
                    name=f'NumPy {version} threshold',
                )
                self.status.setText(
                    f'Completed with NumPy {version} in worker '
                    f'PID {result["worker_pid"]}.'
                )
            elif state == 'canceled':
                self.status.setText('Operation canceled.')
            else:
                self._show_error(task.error or 'Unknown worker failure')
        finally:
            if self._task is task:
                self._task = None
                self._set_busy(False)

    def _show_error(self, error: object, *, notify: bool = False) -> None:
        from napari.plugins.environments import (
            PluginEnvironmentUnavailableError,
        )

        self._task = None
        self._set_busy(False)
        details = str(error)
        if isinstance(error, PluginEnvironmentUnavailableError):
            summary = details.splitlines()[0] if details else ''
            if 'restart napari' not in summary.casefold():
                summary = (
                    f'{summary} Restart napari to retry plugin environment '
                    'setup.'
                ).strip()
            prefix = 'Environment unavailable'
        else:
            summary = details.splitlines()[0] if details else 'Unknown failure'
            prefix = 'Operation failed'
        if len(summary) > 140:
            summary = f'{summary[:137]}…'
        self.status.setText(f'{prefix}: {summary}')
        if notify:
            from napari.utils.notifications import show_error

            show_error(f'Dependency isolation demo failed: {details}')

    def _set_busy(self, busy: bool) -> None:
        self.environment.setEnabled(not busy)
        self.threshold.setEnabled(not busy)
        self.run_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, 0)
        else:
            self.progress.reset()
