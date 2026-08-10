# Migrate an existing plugin

> [!IMPORTANT]
> This page documents the prototype API demonstrated by this repository.
> It is not documentation for a released napari feature.

Use this guide when an existing `npe2` plugin imports packages outside napari's direct base requirements.
Read [Write a plugin with managed environments](writing-a-managed-plugin.md) for the complete manifest, worker-package, task, lifecycle, and validation reference.

Migration is an explicit compatibility contract.
Add `host_dependency_policy: napari` only after the host wheel and host imports satisfy that contract.
Plugins without the field remain legacy plugins and require an explicit unmanaged-install confirmation in the prototype Plugin Manager.

## 1. Inventory dependencies and imports

Classify every runtime import, including imports inside functions and imports performed while constructing a widget.

| Dependency | Destination |
| --- | --- |
| Python standard library, napari, and direct base requirements of napari | Host package; declare every package imported directly |
| Every other runtime package, regardless of size | Managed environment and worker code |
| pytest, linters, documentation tools, and other development tools | Development or testing dependency group |

The outer package's version constraints must accept the exact packages installed with every supported napari version.
A transitive dependency or unrelated package that happens to be installed does not become an allowed host dependency.

NumPy can appear on both sides.
Host code uses napari's NumPy, while an environment recipe may request the version required by its worker dependencies.

Before migration, a segmenter might declare everything together:

```toml
[project]
dependencies = [
    "napari",
    "numpy",
    "qtpy",
    "cellpose==3.1.0",
    "tensorflow==2.16.1",
    "stardist==0.9.2",
]
```

After migration, only allowed, directly imported host packages remain:

```toml
[project]
dependencies = [
    "napari",
    "numpy",
    "qtpy",
]
```

Cellpose, TensorFlow, and StarDist move to their environment recipes.
Do not leave worker packages in the outer metadata as optional fallbacks because a normal resolver could still install them into napari's environment.

## 2. Draw the process boundary

Keep code in the host when it:

- creates or updates a widget;
- accesses a viewer, layer, event, notification, or napari command;
- uses Qt;
- uses only packages supplied by napari.

Move code to a worker when it:

- imports any other runtime package;
- can receive ordinary supported Python values and NumPy arrays;
- can return ordinary supported Python values and NumPy arrays;
- does not need napari or Qt objects.

Moving a heavy import inside a host function is not enough.
The function containing that import must execute as a declared worker command.

For example, this mixed widget runs Cellpose in napari's process:

```python
from cellpose import models
from qtpy.QtWidgets import QWidget


class SegmenterWidget(QWidget):
    def run(self) -> None:
        image = self.viewer.layers.selection.active.data
        model = models.Cellpose(model_type="cyto3")
        labels, *_ = model.eval(image)
        self.viewer.add_labels(labels)
```

After migration, host code submits only values:

```python
import numpy as np

from napari.plugins import execute_worker_command


def run(self) -> None:
    image = np.asarray(self.viewer.layers.selection.active.data)
    self._task = execute_worker_command(
        "napari-segmenter.cellpose",
        image,
        {"model_type": "cyto3"},
    )
    self._task.add_progress_callback(self._on_progress)
    self._task.add_done_callback(self._on_done)
```

The worker imports Cellpose without importing napari or Qt:

```python
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from napari.plugins import WorkerContext


def segment_cellpose(
    image: np.ndarray,
    parameters: dict[str, str],
    *,
    napari_context: WorkerContext,
) -> np.ndarray | None:
    napari_context.update("Loading Cellpose")
    if napari_context.cancel_requested:
        return None

    from cellpose import models

    model = models.Cellpose(model_type=parameters["model_type"])
    napari_context.update("Running Cellpose")
    labels, *_ = model.eval(np.asarray(image))
    return np.asarray(labels)
```

Do not pass the viewer, layer, widget, Qt values, arbitrary objects, generators, files, or callables to the worker.

Pass NumPy arrays directly rather than introducing transport-specific types.
Wetlands automatically copies each array into an operating-system shared-memory segment, sends its descriptor, and reconstructs an independently owned array on the receiving side.
Results follow the same path back to the host, and Wetlands releases the segments after acknowledgement or terminal cleanup.
This copy-in/copy-out design keeps array bytes out of control messages, ensures worker mutation cannot alter the caller's input, and leaves returned arrays valid after worker cleanup.

## 3. Add one embedded worker project

Most existing plugins need a small adapter between ordinary values and a third-party library.
Place all plugin-owned worker adapters in one embedded project:

```text
napari-segmenter/
├── pyproject.toml
└── src/
    └── napari_segmenter/
        ├── __init__.py
        ├── _widget.py
        ├── napari.yaml
        └── worker/
            ├── pyproject.toml
            └── napari_segmenter_worker.py
```

The inner project is dependency-free because `napari.yaml` is the dependency authority:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "napari-segmenter-worker"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = []

[tool.setuptools]
py-modules = ["napari_segmenter_worker"]
```

Add the worker files to the outer wheel's package data:

```toml
[tool.setuptools]
include-package-data = true

[tool.setuptools.package-data]
napari_segmenter = [
    "napari.yaml",
    "worker/pyproject.toml",
    "worker/*.py",
]
```

The plugin author publishes one wheel.
Napari later installs the worker project shipped in that exact wheel into each declared environment.

Omit the embedded project when a declared Conda or PyPI dependency already exports every qualified target the plugin needs.

## 4. Move dependencies into manifest environments

Declare one recipe for each genuinely incompatible dependency set and associate commands with those environments:

```yaml
schema_version: 0.3.0
name: napari-segmenter
display_name: Segmenter
host_dependency_policy: napari
contributions:
  worker_package: worker
  environments:
    - id: napari-segmenter.cellpose
      display_name: Cellpose
      python: "==3.10.*"
      conda:
        - numpy
        - cellpose==3.1.0
      channels:
        - conda-forge

  commands:
    - id: napari-segmenter.cellpose
      title: Segment with Cellpose
      python_name: napari_segmenter_worker:segment_cellpose
      environment: napari-segmenter.cellpose
```

One plugin-wide `worker_package` applies to every declared environment.
Do not repeat it per environment or duplicate its dependencies in the inner `pyproject.toml`.

Split environments according to real dependency incompatibilities, not individual function calls.
Commands sharing one compatible dependency set can share one environment and warm worker.

WSegmenter declares separate Cellpose, StarDist, and SAM 2 environments because they represent independent heavyweight stacks.
Its single embedded adapter project supplies qualified targets to all three.

## 5. Replace direct calls with observable tasks

Update the widget to own one compact status label, progress bar, and cancel control for the command it starts.
Subscribe to `PluginTask` callbacks instead of blocking the Qt thread:

```python
from napari.plugins.environments import PluginTaskState


def cancel(self) -> None:
    if self._task is not None:
        self._task.cancel()


def _on_progress(self, update) -> None:
    self.status.setText(update.message)
    if update.current is None or update.total is None:
        self.progress.setRange(0, 0)
    else:
        self.progress.setRange(0, update.total)
        self.progress.setValue(update.current)


def _on_done(self, task) -> None:
    if task.state is PluginTaskState.COMPLETED:
        self.viewer.add_labels(task.result(), name="Segmentation")
    elif task.state is PluginTaskState.CANCELED:
        self.status.setText("Canceled")
    else:
        self.status.setText(str(task.error or "Worker failed"))
```

Use the shared **Plugin Environments** window for detailed setup and worker logs.
Do not duplicate a scrolling environment log in each plugin widget.

`PluginEnvironmentUnavailableError` means startup did not make the command's environment available for this session.
Tell the user to restart napari to retry setup.
`PluginWorkerError` reports execution or transport failures and may contain a structured remote traceback, exception type, worker process, exit code, signal, timeout, or serialization context.

## 6. Account for the restart lifecycle

Package and enablement changes take effect after restart.
At startup, napari reconciles all enabled plugin environments before their commands become available.
Calling a command never provisions an environment lazily.

During setup, users can cancel the complete pass and continue after cleanup, or quit napari.
After failure they can retry, continue without affected commands, or quit.
If an environment was skipped and the plugin remains enabled, napari retries at the next launch.

The first command starts a worker lazily after setup succeeds.
Later commands reuse the warm worker until the user stops it or napari exits.

Describe large downloads and expected first-run costs in the plugin release notes.
When worker source or an environment recipe changes, release a new plugin version and expect napari to rebuild the affected environment at startup.

## 7. Validate the built wheel

Validate the manifest and authoritative wheel metadata:

```console
npe2 validate src/napari_segmenter/napari.yaml
python -m build
npe2 validate --host-dependencies dist/napari_segmenter-1.0.0-py3-none-any.whl
python -m zipfile --list dist/napari_segmenter-1.0.0-py3-none-any.whl
```

Confirm that the wheel contains the manifest, inner `pyproject.toml`, and worker source.
Test a built wheel in a clean installation because editable source tests can hide missing package data.

Choose and test an accurate lower bound for napari and `npe2` after the prototype schema and runtime are released.
Do not publish a migrated plugin against unreleased APIs as though they were stable.

## Migration checklist

- [ ] Inventory host, worker, and development dependencies.
- [ ] Keep every napari and Qt interaction in host code.
- [ ] Move every additional runtime import and its computation to worker code.
- [ ] Exchange only supported ordinary values and NumPy arrays, relying on automatic shared-memory array transport instead of transport-specific code.
- [ ] Add one dependency-free embedded worker project only when adapter targets are needed.
- [ ] Include the manifest and worker project in the built wheel.
- [ ] Declare worker dependencies once in manifest environments.
- [ ] Give every worker command a qualified target and same-plugin environment.
- [ ] Add `host_dependency_policy: napari` only after the host contract is satisfied.
- [ ] Present command progress, cancellation, completion, and concise failures in the widget.
- [ ] Validate the built wheel's authoritative host requirements.
- [ ] Test isolation, transport, progress, cancellation, failures, reuse, rebuilding, stopping workers, and shutdown.
- [ ] Document the restart boundary and first-time environment cost.
- [ ] State that managed environments isolate dependencies but do not sandbox untrusted code.
