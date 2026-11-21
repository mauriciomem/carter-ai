"""Help epilogs for a dotfile-managed ``~/.gitconfig``.

Carter never writes a symlinked or read-only global git config, and its warnings are one line
(``! ~/.gitconfig is a symlink: add Carter's include line``). The line itself, and why it is
needed, live here, in ``carter install --help``, ``carter guard install --help`` and
``carter uninstall --help``. Plain constants: ``carter --help`` imports this on every run.
"""

from __future__ import annotations

# ``\b`` keeps click from re-wrapping the lines that follow it.
INSTALL_EPILOG = """\b
Dotfile-managed ~/.gitconfig (a symlink or read-only file):
Carter never edits it. Add this to your dotfiles once; it never changes, and Carter
recognises it in any spelling (~/ or absolute path, or inside a file you include):

\b
  [include]
      path = ~/.carter/gitconfig

Until the line is there the git hooks are inactive; `carter guard status` says so.
"""

UNINSTALL_EPILOG = """\b
Dotfile-managed ~/.gitconfig (a symlink or read-only file):
Carter does not edit it. If you added Carter's include line there, delete it from
your dotfiles:

\b
  [include]
      path = ~/.carter/gitconfig
"""
