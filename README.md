# Conflict-free napari plugins

This demo explores a plugin model in which installing a conforming plugin cannot change napari's dependencies or conflict with another plugin.
The plugin's napari and Qt integration stays in the napari process, while code that needs additional dependencies runs in persistent, isolated worker environments.
Legacy plugins remain installable, but napari warns before allowing one to resolve dependencies into the napari environment.

The repository includes a small plugin that runs the same operation with incompatible NumPy versions and WSegmenter as a realistic integration using Cellpose, StarDist, and SAM 2.
The prototype and demo were generated with GPT-5.6 Sol and reviewed with automated tests and manual use.

## Run the demo

Run:

```console
uv run demo.py
```

While developing from the coordinated local worktrees, run `uv run demo_local.py` instead.

The launcher installs the small isolation plugin before napari starts.
On the first launch, napari checks every declared worker environment and installs the missing ones sequentially.
The **Setting up plugin environments** dialog opens when installation work begins and shows progress and logs.

Environments are persistent: later launches compare each installed environment with the plugin declaration and reuse it when nothing changed.
If every environment is current, startup remains silent.

## Try dependency isolation

1. Open **Plugins > Isolation Demo > Dependency isolation demo**.
2. Select **NumPy 1.26**, then run the threshold operation.
3. Select **NumPy 2.2** and run the same operation again.

The plugin is installed only once in napari, but each command runs with its declared NumPy version in a separate process.
Images, labels, and ordinary nested Python values cross the process boundary without exposing transport code to the plugin widget.

## Install WSegmenter from Git

WSegmenter is intentionally not published on PyPI.
Install the demo source through the Plugin Manager's explicitly unmanaged path:

1. Open **Plugins > Install/Uninstall Plugins...**.
2. Paste the following requirement into the direct-install field:

   ```text
   git+https://github.com/arthursw/napari-plugin-environments-demo.git@d770ef509066a90ccec167f4b75298d2e222a78a#subdirectory=plugins/napari-wsegmenter
   ```

3. Start the installation and accept the unmanaged-install warning.
4. Close the Plugin Manager and observe the restart prompt.
5. Close napari, then restart the existing script environment without synchronizing away the newly installed plugin:

   ```console
   uv run --no-sync demo.py
   ```

The startup dialog installs WSegmenter's three declared environments before its commands become available.
Open **Plugins > WSegmenter** to try Cellpose, StarDist, or SAM 2.
The widgets and napari integration remain lightweight host code, while the heavy imports and segmentation run in their respective worker environments.

The installation is called unmanaged because a Git requirement asks pip to build source and perform normal dependency resolution.
This warning concerns the installation path, not WSegmenter's worker isolation design.
The safe managed installation path is reserved for one immutable, validated wheel obtained from the plugin catalog.

## Inspect and stop workers

Open **Plugins > Managed Plugin Workers...** to inspect environment status and logs.
Worker processes start only when a command first needs them, so startup does not import heavy libraries or reserve worker memory.
Napari keeps each process alive after the command completes, which makes later calls faster because the process and imported model libraries can be reused.
Use **Stop** on an idle worker to release that memory; the next command starts a fresh worker in the already installed environment.

## Try a legacy catalog plugin

Open **Plugins > Install/Uninstall Plugins...** and select a legacy plugin from the catalog.
After downloading and inspecting its wheel, the Plugin Manager warns that the plugin has not opted in to napari-compatible host dependencies and may change packages in the napari environment.
Cancel the installation unless you deliberately want to test that unmanaged path.

A conforming catalog wheel is validated before installation and installed without resolving new host dependencies.

## Why plugin changes require a restart

Installing, updating, uninstalling, enabling, or disabling a plugin changes the set of declarations that napari must trust for the whole session.
Napari therefore keeps one immutable snapshot while it is running and asks for a restart after a Plugin Manager change.
At the next startup, it installs or rebuilds every environment required by the new snapshot, removes environments left by uninstalled plugins, and shows one progress dialog when that work changes disk state.

Supporting those changes in a running process would require coordinating package installation, environment replacement and removal, active workers, queued and running commands, cancellation, rollback, and plugin discovery at the same time.
The restart boundary deliberately avoids those concurrency cases and makes the guarantee understandable: commands run only after one complete startup reconciliation has succeeded.

## If environment setup fails

The startup dialog offers three choices:

- **Retry** cleans up the incomplete environment and attempts a clean installation again.
- **Continue without affected plugin workers** opens napari with successfully prepared workers still available; commands belonging to failed environments remain unavailable for that session.
- **Quit napari** cancels setup and closes the application.

Continuing is a session-only decision.
If the plugin remains enabled and its environment still cannot be installed, napari presents the failure again at the next startup.
To stop retrying, uninstall or disable the affected plugin in the Plugin Manager and restart napari; startup then removes its orphaned managed environments.

## Run the automated check

Close the interactive demo first, then run:

```console
uv run smoke.py
```

The smoke test verifies incompatible dependencies, separate and reusable workers, arrays and nested values, progress, cancellation, structured failures, and an unchanged host environment.

Managed environments provide dependency isolation, not a security sandbox.
