from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from napari.plugins import WorkerContext


def threshold(
    image: np.ndarray,
    parameters: dict[str, Any],
    *,
    napari_context: WorkerContext,
) -> dict[str, Any] | None:
    """Return labels and diagnostics from the isolated NumPy environment."""

    napari_context.update('Thresholding image', current=0, maximum=2)
    if napari_context.cancel_requested:
        return None
    value = float(parameters['threshold'])
    labels = (np.asarray(image) > value).astype(np.uint8)
    napari_context.update('Returning labels', current=1, maximum=2)
    if napari_context.cancel_requested:
        return None
    return {
        'labels': labels,
        'numpy_version': np.__version__,
        'worker_pid': os.getpid(),
        'metadata': {
            'shape': tuple(labels.shape),
            'threshold': value,
            'values': [int(labels.min()), int(labels.max())],
        },
    }


def slow_operation(
    steps: int,
    delay: float,
    *,
    napari_context: WorkerContext,
) -> dict[str, Any] | None:
    """Run long enough for the caller to verify cooperative cancellation."""

    for index in range(steps):
        napari_context.update(
            'Running cancellable operation', current=index, maximum=steps
        )
        if napari_context.cancel_requested:
            return None
        time.sleep(delay)
    return {'worker_pid': os.getpid(), 'steps': steps}


def fail_operation(*, napari_context: WorkerContext) -> None:
    """Raise a predictable remote exception for the smoke test."""

    napari_context.update('Raising demonstration failure')
    raise RuntimeError('intentional managed-worker demonstration failure')
