"""Entry point for the frozen (PyInstaller) desktop build.

The pip-installed CLI keeps using ``privacy_firewall.__main__:entry_point``
unchanged; this module only exists so the packaged app behaves sensibly when
it is *double-clicked* rather than run from a shell:

* No arguments (the double-click case) launches the Studio dashboard on a
  stable workspace folder, because the process working directory for a
  double-launched app is not somewhere the user keeps documents.
* Any arguments fall through to the normal Typer CLI, so the bundled binary
  is still a complete command-line tool (``PrivacyFirewall detect x.pdf``).

The console window is intentionally kept (see ``packaging/README.md``): it is
where ``run_studio`` prints the local URL and any startup failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE_DIR_NAME = "PrivacyFirewall"
"""Folder created under the user's Documents to hold documents and uploads."""


def default_workspace() -> Path:
    """Return (creating if needed) the workspace used for a no-argument launch.

    Prefers ``~/Documents/PrivacyFirewall`` and falls back to
    ``~/PrivacyFirewall`` on systems without a Documents folder.

    Returns:
        The workspace directory, guaranteed to exist.
    """
    documents = Path.home() / "Documents"
    base = documents if documents.is_dir() else Path.home()
    workspace = base / WORKSPACE_DIR_NAME
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _pause(message: str) -> None:
    """Show *message* and hold the console open so a double-click user can read it."""
    print(message, file=sys.stderr)
    try:
        input("\nPress Enter to close this window...")
    except (EOFError, KeyboardInterrupt):  # pragma: no cover - no console attached
        pass


def main() -> None:
    """Run the packaged app: CLI when given arguments, Studio when not."""
    if len(sys.argv) > 1:
        from privacy_firewall.__main__ import entry_point

        entry_point()
        return

    from privacy_firewall.ui.studio import run_studio

    workspace = default_workspace()
    print(f"Workspace: {workspace}")
    try:
        run_studio(workspace, open_browser=True)
    except KeyboardInterrupt:
        print("\nStopped.")
    except SystemExit as exc:
        # run_studio raises SystemExit(str) when the port is already bound.
        if exc.code not in (None, 0):
            _pause(str(exc.code))
    except Exception as exc:  # noqa: BLE001 - last resort so the window doesn't vanish
        _pause(f"Privacy Firewall failed to start: {exc}")


if __name__ == "__main__":
    main()
