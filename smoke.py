# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = [
#   "napari[optional,pyqt6] @ git+https://github.com/arthursw/napari.git@demo/plugin-environments",
#   "napari-isolation-demo @ git+https://github.com/arthursw/napari-plugin-environments-demo.git@main#subdirectory=plugins/napari-isolation-demo",
#   "napari-plugin-manager @ git+https://github.com/arthursw/napari-plugin-manager.git@demo/plugin-environments",
#   "npe2",
#   "wetlands==2.3.3",
# ]
# [tool.uv]
# override-dependencies = [
#   "npe2 @ git+https://github.com/arthursw/npe2.git@demo/plugin-environments",
# ]
# ///

import os
import tempfile
import threading
from pathlib import Path

import npe2
import numpy as np
from napari.plugins import execute_worker_command
from napari.plugins._environment_manager import (
    PluginEnvironmentManager,
    _set_plugin_environment_manager,
)
from napari.plugins.environments import (
    PluginTaskCanceledError,
    PluginWorkerError,
)


def reconcile_startup(manager: PluginEnvironmentManager) -> None:
    """Perform the startup step normally scheduled by napari's first window."""

    manager.start_reconciliation().result(timeout=900)


def _run_smoke(root: Path) -> None:
    npe2.PluginManager.instance().discover(include_npe1=False)
    host_pid = os.getpid()
    host_numpy = np.__version__
    image = np.arange(64, dtype=np.float32).reshape(8, 8) / 63
    progress: list[str] = []
    manager = PluginEnvironmentManager(root=root)
    _set_plugin_environment_manager(manager)

    try:
        reconcile_startup(manager)
        first_task = execute_worker_command(
            'napari-isolation-demo.threshold_numpy2',
            image,
            {'threshold': 0.5},
        )
        first_task.add_progress_callback(
            lambda update: progress.append(update.message)
        )
        first = first_task.result(timeout=900)
        reused = execute_worker_command(
            'napari-isolation-demo.threshold_numpy2',
            image,
            {'threshold': 0.5},
        ).result(timeout=120)
        incompatible = execute_worker_command(
            'napari-isolation-demo.threshold_numpy1',
            image,
            {'threshold': 0.5},
        ).result(timeout=900)

        assert first['numpy_version'] == '2.2.6'
        assert incompatible['numpy_version'] == '1.26.4'
        assert first['worker_pid'] == reused['worker_pid']
        assert len({first['worker_pid'], incompatible['worker_pid']}) == 2
        assert host_pid not in {
            first['worker_pid'],
            incompatible['worker_pid'],
        }
        assert np.__version__ == host_numpy
        np.testing.assert_array_equal(
            first['labels'], (image > 0.5).astype(np.uint8)
        )
        assert first['metadata']['shape'] == image.shape
        assert 'Thresholding image' in progress

        running = threading.Event()
        cancel_task = execute_worker_command(
            'napari-isolation-demo.slow', 400, 0.025
        )
        cancel_task.add_progress_callback(
            lambda update: (
                running.set()
                if update.message == 'Running cancellable operation'
                else None
            )
        )
        assert running.wait(120)
        cancel_task.cancel('Requested by smoke test')
        try:
            cancel_task.result(timeout=120)
        except PluginTaskCanceledError:
            pass
        else:
            raise AssertionError('Worker cancellation did not complete')

        try:
            execute_worker_command('napari-isolation-demo.fail').result(
                timeout=120
            )
        except PluginWorkerError as error:
            if 'intentional managed-worker' not in str(error):
                raise AssertionError(
                    'Remote failure lost its original message'
                ) from error
        else:
            raise AssertionError('Remote failure was not preserved')

    finally:
        manager.close()
        _set_plugin_environment_manager(None)

    print('Isolation smoke test passed.')
    print(f'Host NumPy: {host_numpy}')
    print('Worker NumPy versions: 1.26.4 and 2.2.6')
    print('Reuse, transport, progress, cancellation, and failure: OK')


def main() -> None:
    with tempfile.TemporaryDirectory(
        prefix='napari-plugin-environments-demo-'
    ) as directory:
        _run_smoke(Path(directory))


if __name__ == '__main__':
    main()
