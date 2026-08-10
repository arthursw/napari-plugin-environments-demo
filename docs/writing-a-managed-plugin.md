# Write a plugin with managed environments

> [!IMPORTANT]
> This page documents the prototype API demonstrated by this repository.
> It is not documentation for a released napari feature.

Managed environments let a plugin keep its napari and Qt integration in the napari process while dependency-sensitive computation runs in an isolated worker process.
Each plugin owns its environment recipes, while napari owns provisioning, worker processes, progress, cancellation, failures, reuse, and shutdown.
NumPy array data crosses the process boundary automatically through operating-system shared memory, while plugin functions continue to receive and return ordinary `numpy.ndarray` objects.

The [minimal isolation plugin](../plugins/napari-isolation-demo/) demonstrates the complete pattern with incompatible NumPy versions.
[WSegmenter](https://github.com/arthursw/napari-wsegmenter/tree/demo/plugin-environments) applies the same pattern to Cellpose, StarDist, and SAM 2.

## Separate host code from worker code

A managed-compatible plugin has two execution locations:

- **Host code** is installed alongside napari and runs in the napari process.
  It creates widgets, reads layer data, calls napari and Qt APIs, submits worker commands, and applies results to the viewer.
- **Worker code** runs in a separate process created from a declared environment.
  It imports packages not supplied by napari and exchanges ordinary supported Python values and NumPy arrays with host code.

Code running in the host may rely only on Python's standard library, the plugin's own host modules, napari, and packages that are direct base requirements of napari on the current platform.
The outer plugin package must still declare every allowed package that its host code imports directly, and each version constraint must accept the version installed with napari.

Every other runtime dependency belongs in a managed environment, together with the code that imports it.
This is a strict placement rule even for packages that are small or appear unlikely to conflict.

Plugin code using a viewer, layer, widget, notification, Qt object, or another napari API must remain in the host process.
Pass layer data to workers as arrays and update the viewer after the worker returns.

## Use one embedded worker project

The recommended layout contains one small worker distribution inside the main plugin package:

```text
napari-threshold/
├── pyproject.toml
└── src/
    └── napari_threshold/
        ├── __init__.py
        ├── _widget.py
        ├── napari.yaml
        └── worker/
            ├── pyproject.toml
            └── napari_threshold_worker.py
```

The inner project is not another napari plugin and is not published separately.
It needs no manifest, entry point, README, `__init__.py`, or additional `src` directory for a single-module worker.
Napari installs it into each environment declared by the plugin, but never into the environment running napari.

The plugin author still builds and publishes one outer wheel.
That wheel contains the lightweight host package, the manifest, and the inner worker project as package data.
Installing the outer wheel makes the worker source available to napari but does not install its worker dependencies into the napari environment.
During startup reconciliation, napari uses the manifest to build each isolated environment and installs both its declared dependencies and the embedded worker project there.

Omit the embedded project when every worker target is already provided by a package declared in the environment recipe.

## Configure the outer plugin package

The root `pyproject.toml` describes the plugin installed with napari:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "napari-threshold"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "napari",
    "numpy",
    "qtpy",
]

[project.entry-points."napari.manifest"]
napari-threshold = "napari_threshold:napari.yaml"

[tool.setuptools]
include-package-data = true

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
napari_threshold = [
    "napari.yaml",
    "worker/pyproject.toml",
    "worker/*.py",
]
```

The package-data declaration is essential because host code does not import the worker module.
Without it, an editable checkout may work while the wheel installed by users omits the worker source.

Do not add worker-only dependencies to the outer `dependencies` list.
Napari's managed installation validates the selected wheel's authoritative `Requires-Dist` metadata against the running napari installation and installs the accepted wheel without dependency resolution.
Direct `pip`, Conda, and source installations remain outside that host-environment guarantee.

The [Plugin Manager prototype documentation](https://github.com/arthursw/napari-plugin-manager/blob/8e09dcff6c3435a5e5c17f36d8af4c481bad1289/README.md) explains exact-wheel validation, legacy warnings, unmanaged installation, and restart behavior.

## Configure the embedded worker project

Create `src/napari_threshold/worker/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "napari-threshold-worker"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = []

[tool.setuptools]
py-modules = ["napari_threshold_worker"]
```

The empty dependency list is intentional.
The manifest is the single authoritative declaration of worker runtime dependencies, so the inner project must not declare runtime, optional, or dynamic dependencies.
Its distribution name must also differ from every Conda and PyPI dependency declared by the plugin.

The distribution name only identifies the inner build artifact.
Because the project has no `napari.manifest` entry point, napari does not discover it as a second plugin.

## Write a qualified worker target

Create `src/napari_threshold/worker/napari_threshold_worker.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from napari.plugins import WorkerContext


def threshold(
    image: np.ndarray,
    parameters: dict[str, float],
    *,
    napari_context: WorkerContext,
) -> dict[str, object] | None:
    napari_context.update("Thresholding image", current=0, maximum=2)
    if napari_context.cancel_requested:
        return None

    value = parameters["threshold"]
    labels = (np.asarray(image) > value).astype(np.uint8)

    napari_context.update("Returning labels", current=2, maximum=2)
    if napari_context.cancel_requested:
        return None

    return {
        "labels": labels,
        "numpy_version": np.__version__,
        "metadata": {"shape": image.shape, "threshold": value},
    }
```

The `TYPE_CHECKING` import gives static type information without adding napari as a worker dependency.
Napari supplies the reserved keyword-only `napari_context` argument to worker commands by default.
Set `accepts_worker_context: false` only when a target deliberately omits it.

Call `update()` to report progress and check `cancel_requested` at safe interruption points.
A third-party call that does not return or expose cancellation points cannot always stop cooperatively.

Targets must be qualified, importable module-level callables such as `napari_threshold_worker:threshold`.
Do not submit lambdas, closures, bound methods, or serialized callable objects.

## Declare environments and worker commands

Connect the environment, target, and host widget in `napari.yaml`:

```yaml
schema_version: 0.3.0
name: napari-threshold
display_name: Threshold
host_dependency_policy: napari
contributions:
  worker_package: worker
  environments:
    - id: napari-threshold.numpy2
      display_name: NumPy 2.2
      python: "==3.10.*"
      conda:
        - numpy==2.2.6
      channels:
        - conda-forge

  commands:
    - id: napari-threshold.run
      title: Threshold with NumPy 2.2
      python_name: napari_threshold_worker:threshold
      environment: napari-threshold.numpy2
    - id: napari-threshold.make_widget
      title: Create threshold widget
      python_name: napari_threshold._widget:ThresholdWidget

  widgets:
    - command: napari-threshold.make_widget
      display_name: Threshold
```

`host_dependency_policy: napari` opts into the host dependency contract.
Environment and isolated-command identifiers must begin with the manifest name and are unique under case-insensitive comparison.
A worker command can reference only an environment declared by the same plugin.

`worker_package: worker` is a path relative to the directory containing `napari.yaml`.
It must point to the embedded Python project containing its own `pyproject.toml`.
The command's `python_name` is resolved inside the selected worker environment; napari does not import that target in the host process.

Use `conda` for Conda requirements, `pypi` for Python package requirements, and `channels` for Conda channel order.
The `python` field accepts comma-separated PEP 440 clauses using `==`, `!=`, `>=`, `<=`, `>`, or `<`, such as `==3.10.*`; `~=` and `===` are not supported.
Conda entries use a package name followed only by those comparison operators, and the interpreter belongs in the top-level `python` field rather than the `conda` list.
PyPI entries use PEP 508 requirements without environment markers.
Direct PyPI references are limited to credential-free `git+https` URLs pinned to a complete 40-character commit hash, with no query or fragment.
Channels must be named channels rather than URLs, and `conda-forge` is used when `channels` is omitted.
Declare each distribution at most once in an environment and never in both dependency lists.

Schema 0.3 deliberately has one plugin-wide `worker_package` and no per-environment local-package or lockfile fields.
Napari identifies worker content when deciding whether the persistent environment can be reused.

Worker commands cannot directly implement widget, reader, writer, or sample-data contributions because those contributions use host-process protocols and napari values.
Contribute host code that invokes the worker command instead.

See the demo's actual [manifest](../plugins/napari-isolation-demo/src/napari_isolation_demo/napari.yaml), [host widget](../plugins/napari-isolation-demo/src/napari_isolation_demo/_widget.py), and [worker module](../plugins/napari-isolation-demo/src/napari_isolation_demo/worker/napari_isolation_worker.py).

## Invoke a worker without blocking Qt

`execute_worker_command()` returns immediately with a `PluginTask`:

```python
import numpy as np

from napari.plugins import execute_worker_command
from napari.plugins.environments import PluginTaskState


def run(self) -> None:
    image = np.asarray(self.viewer.layers.selection.active.data)
    self.run_button.setEnabled(False)
    self.cancel_button.setEnabled(True)
    self.progress_bar.setRange(0, 0)

    self._task = execute_worker_command(
        "napari-threshold.run",
        image,
        {"threshold": self.threshold.value()},
    )
    self._task.add_progress_callback(self._on_progress)
    self._task.add_done_callback(self._on_done)


def cancel(self) -> None:
    if self._task is not None:
        self._task.cancel("Canceled from the threshold widget")


def _on_progress(self, update) -> None:
    self.status_label.setText(update.message)
    if update.current is None or update.total is None:
        self.progress_bar.setRange(0, 0)
    else:
        self.progress_bar.setRange(0, update.total)
        self.progress_bar.setValue(update.current)


def _on_done(self, task) -> None:
    self.run_button.setEnabled(True)
    self.cancel_button.setEnabled(False)

    if task.state is PluginTaskState.COMPLETED:
        result = task.result()
        self.viewer.add_labels(result["labels"], name="Threshold")
    elif task.state is PluginTaskState.CANCELED:
        self.status_label.setText("Canceled")
    else:
        self.status_label.setText(str(task.error or "Worker failed"))
```

Do not call `task.result()` on the Qt main thread before the task is done.
Use callbacks, or await the task from an async integration.
When napari's Qt application is running, callbacks are dispatched on the GUI thread so they can update widgets and layers.

Keep progress and cancellation beside the action that started the worker command.
Use **Plugins > Manage Plugin Environments...** for shared setup and worker diagnostics rather than adding a scrolling environment log to every plugin widget.

## Understand queues, cancellation, and failures

Once started, each environment owns one persistent worker process, and commands using that environment run one at a time in submission order.
Different environments can run work concurrently.

`task.cancel()` returns whether the request was accepted.
Canceling a queued task removes it from the queue and completes it as canceled without starting the worker call.
Canceling a running task sets the worker cancellation flag exposed as `napari_context.cancel_requested`; the target must return from its current Python or third-party call before cancellation can complete.
Cancellation is therefore cooperative and does not forcibly interrupt a blocking library call, although a result produced after cancellation was requested is discarded.

An unavailable environment produces an already-failed task, so always attach a done callback and inspect its terminal state.
Remote exceptions and serialization errors fail only their task and normally leave the worker reusable.
A fatal transport error or dead worker stops that worker and fails its queued tasks without replaying them; a later submission starts a fresh worker after cleanup completes.
Napari never retries a worker command automatically, so plugin code should offer an explicit retry only when repeating the operation is safe.

## Pass arrays through automatic shared-memory transport

Plugin code passes NumPy arrays directly to `execute_worker_command()` and returns arrays directly from the worker target.
It does not allocate shared memory, serialize array bytes, pass shared-memory names, or release transport resources.

Underneath that ordinary Python API, napari's Wetlands backend transports array data out of band:

1. The sending process copies the array into an operating-system shared-memory segment and sends a small descriptor containing its shape, dtype, and segment identity.
2. The receiving process attaches to the segment and copies its contents into a writable, C-contiguous `numpy.ndarray` owned by that process.
3. The receiver acknowledges the transfer, and the process that created the segment closes and unlinks it.

Results use the same mechanism in the opposite direction.
The host receives an independently owned array before the worker-owned segment is released, so the result remains valid after the task or worker pool ends.
Mutating a worker input does not mutate the caller's original array.

This is automatic shared-memory **transport**, not shared mutable array ownership and not an end-to-end zero-copy API.
The copies give plugin code simple ownership semantics while keeping large array bytes out of the normal control-message serialization path.
Wetlands owns the segment leases and cleans them up after completion, cancellation, timeout, dispatch failure, disconnection, or worker death.

## Pass supported values

Arguments and results can contain:

- `None`, booleans, integers, floats, strings, and bytes;
- lists and tuples containing supported values;
- dictionaries with supported scalar keys and supported values;
- NumPy arrays without object dtype or dtype metadata and within transport limits.

Arrays nested inside supported lists, tuples, and dictionaries use the same automatic shared-memory transport.
Non-contiguous arrays become C-contiguous copies, empty arrays need no shared-memory allocation, arrays may have at most 64 dimensions, and one array must fit within the operating system's shared-memory limits.
Both the napari process and worker environment need NumPy; napari already provides it to the host, so declare it in every managed environment that receives or returns arrays.
Cyclic containers are rejected.

Do not pass viewers, layers, widgets, Qt objects, generators, arbitrary class instances, open files, or callables.
Extract arrays and ordinary metadata in host code, then reconstruct or update napari objects after completion.

## Understand installation and reuse

Installing, updating, uninstalling, enabling, or disabling a plugin requires restarting napari.
At the next launch, napari takes one immutable snapshot of enabled plugin declarations and reconciles every declared environment sequentially.
It reuses unchanged environments silently, builds missing or changed environments, and removes environments left by uninstalled plugins.

The setup dialog appears only when reconciliation mutates disk or needs attention.
While setup is running, users can cancel the complete setup pass and continue into napari after cleanup, or quit napari.
After a failure, users can retry, continue without unavailable worker commands, or quit.
Skipped environments are retried at the next launch if their plugin remains enabled.

Calling `execute_worker_command()` never installs, repairs, rebuilds, or removes an environment.
The first command for a ready environment starts a worker lazily; later commands reuse that warm process.
The **Plugin Environments** window can stop an idle worker without deleting its persistent environment.
Napari closes every owned worker and transport resource during application shutdown.

Environment data is stored below napari's platform-specific user-data directory in `plugin-environments/installations/<hash-of-sys.prefix>/` so independent napari installations do not reconcile one another's environments.

## Validate and test the artifact

Validate the source manifest while developing:

```console
npe2 validate src/napari_threshold/napari.yaml
```

Build and inspect the wheel before release:

```console
python -m build
npe2 validate --host-dependencies dist/napari_threshold-0.1.0-py3-none-any.whl
python -m zipfile --list dist/napari_threshold-0.1.0-py3-none-any.whl
```

Confirm that the wheel includes `napari.yaml`, the inner `pyproject.toml`, and every worker source file.
The built-wheel host check is required because final `Requires-Dist` metadata, not a nearby source `pyproject.toml`, is authoritative.

Test at least:

- importing and constructing host widgets without importing worker-only dependencies;
- command selection and callback behavior;
- arrays and nested supported values crossing the boundary;
- progress, queued and running cancellation, and structured failures;
- unchanged recipe reuse and changed recipe or worker-content rebuilding;
- two plugins or environments using incompatible dependency versions without changing napari's environment;
- stopping idle workers and application shutdown;
- the built wheel in a clean napari installation.

Managed environments isolate dependencies and process lifecycles.
They are not security sandboxes: worker code runs with the user's operating-system permissions and can access the same files and network resources as other trusted plugin code.
