"""``carter check --host``: read-only checks of the machine, from the human's terminal.

RFC-0007 App B §3, the items that exist in slice 1G. It prints names, never values: no
environment values, no tokens, no provider settings (``opencode debug config`` is compared
in memory). Every item has a level: ``ok``, ``info``, ``warn`` or ``red``; the exit code is 1
only if something is ``red``. Items that need the plugin, hooks or isolation (slice 2a/2b)
say so ("not installed in this slice"), never green.

Nothing here writes. The same pieces back ``carter guard status``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from carter import ghtoken, harness
from carter.checkitems import Item, exit_code
from carter.checkitems import render as render_items
from carter.guard import consent, gitconfig, optout, permissions
from carter.guard.configwrite import Reader, missing_statements, target_path
from carter.guard.state import GuardState, load_or_empty_readonly
from carter.identity import ConfigError, load_identity
from carter.identity.errors import E_POLICIES_MISSING, E_STATE_INVALID
from carter.identity.policyset import Statement, consent_groups
from carter.identity.rules import load_rules
from carter.install.jsonc import _load_jsonc
from carter.install.mcp import config_target
from carter.install.paths import guard_state_path

BROKEN_CONFIG_HINT = (
    "A broken OpenCode config drops all policies and your providers: run `carter guard install`."
)
STATE_HINT = "Carter does not rebuild it: fix or move the file, then run `carter guard install`."
CARTER_KEYS_NA = (
    "carter.tier, carter.llmEmail, carter.llmFingerprint and the cap mirror: "
    "not applicable in this slice"
)
HOOK_MODES = {
    "include": "hooks from an included file are reported `global` here",
    "direct": "hooks work but not via include: the direct-write fallback would be used",
    "no-config-hooks": "no config-based hooks (git < 2.54): per-repo fallback (slice 2a)",
}
PLUGIN_ABSENT = (
    "plugin not installed (slice 2a): gate, isolation and signing guards are inactive; "
    "policies are literal denies only"
)


__all__ = ["exit_code", "render", "run_host_checks"]

MCP_FILE_TOKEN = "{file:~/.carter/secrets/gh-read.token}"


def render(items: list[Item]) -> list[str]:
    return render_items(items, "carter check --host (read-only)", "Host")


def _statements_from_records(state: GuardState) -> list[Statement]:
    return [
        Statement(p["id"], "config-edit", p["action"], p["resource"], p["effect"], "")
        for p in state.opencode_policies
        if p["id"].startswith("optout-")
    ]


def _policies(state: GuardState, reader: Reader | None, home: str) -> list[Item]:
    accepted = consent.accepted_groups(state)
    expected = consent.desired_statements(state, home=home, optouts=_statements_from_records(state))
    try:
        loaded = (reader or harness.read_debug_config)()
    except harness.DebugConfigError as exc:
        return [Item("red", "policies", f"cannot read `opencode debug config` ({exc})")]
    items = []
    missing = missing_statements(loaded, expected)
    for s in missing:
        text = f"{E_POLICIES_MISSING}: `{s.id}` is not loaded"
        items.append(Item("red", "policies", text, BROKEN_CONFIG_HINT))
    if expected and not missing:
        items.append(
            Item("ok", "policies", f"{len(expected)} statement(s) loaded ({', '.join(accepted)})")
        )
    path = Path(state.opencode_config) if state.opencode_config else target_path(None)
    config = _load_jsonc(path) if path.exists() else None
    if isinstance(config, dict):
        defined = {str(k) for key in ("providers", "provider") for k in (config.get(key) or {})}
        lost = sorted(defined - harness.provider_ids(loaded))
        if lost:
            items.append(Item("red", "providers", f"not loaded by OpenCode: {', '.join(lost)}"))
        for rec in state.owned_permissions():
            if not permissions.present(config, rec):
                label = f"{rec['agent']}:{rec['key'].removeprefix(permissions.KEY_PREFIX)}"
                items.append(Item("red", "per-agent denies", f"{label} is missing from the config"))
    return items


def _files(state: GuardState) -> list[Item]:
    items = []
    for rec in state.files:
        path = Path(rec["path"])
        if state.owned_unchanged(path):
            items.append(Item("ok", "guard files", f"{path} matches guard-state.json"))
        else:
            what = "was changed since Carter wrote it" if path.exists() else "is missing"
            items.append(
                Item("red", "guard files", f"{path} {what}", "Run `carter guard install`.")
            )
    return items


def _git(state: GuardState) -> list[Item]:
    items = []
    rec = state.gitconfig
    if rec is None and not state.git_config:
        items.append(
            Item("info", "git", "include.path: not needed yet (no Carter git keys; slice 2a)")
        )
    if rec is not None:
        cfg, value = Path(rec["file"]), rec["value"]
        if cfg.exists() and gitconfig.has_include_line(cfg, value):
            items.append(Item("ok", "git", f"include.path for {value} is present"))
        else:
            line = f"git config --global --add include.path {value}"
            items.append(
                Item("red", "git", f"include.path for {value} is missing from {cfg}", line)
            )
        if Path(value).exists() and not gitconfig.parses(Path(value)):
            text = f"{value} is not valid git config: every git command fails while it is included"
            items.append(Item("red", "git", text, "Fix the file or run `carter guard remove`."))
    for r in state.git_config:
        items.append(
            Item("info", "git", f"key {r['key']} written directly (fallback) in {r['file']}")
        )
    try:
        mode = gitconfig.probe_scope()
    except gitconfig.GitError as exc:
        items.append(Item("red", "git", str(exc)))
    else:
        text = HOOK_MODES[mode]
        items.append(Item("info", "git", f"Carter installs no hooks in this slice; {text}"))
    items.append(Item("info", "git", CARTER_KEYS_NA))
    return items


def _project_scope(cwd: Path) -> list[Item]:
    """D48: a project config that can run code is worth a line (names only)."""
    risky = {"plugin", "plugins", "mcp", "commands", "command", "formatter", "shell"}
    found: list[str] = []
    for name in (
        "opencode.json",
        "opencode.jsonc",
        ".opencode/opencode.json",
        ".opencode/opencode.jsonc",
    ):
        path = cwd / name
        data = _load_jsonc(path) if path.is_file() else None
        if isinstance(data, dict) and risky & data.keys():
            found.append(f"{name} ({', '.join(sorted(risky & data.keys()))})")
    for sub in ("plugins", "plugin", "tools", "commands"):
        if (cwd / ".opencode" / sub).is_dir():
            found.append(f".opencode/{sub}/")
    if not found:
        return []
    return [
        Item("warn", "project", "project-scope OpenCode config can run code: " + "; ".join(found))
    ]


def _optouts() -> list[Item]:
    try:
        found = optout.active_optouts(load_identity())
    except ConfigError:
        return [Item("warn", "D52 opt-outs", "config.toml is invalid; opt-outs not listed")]
    items = [
        Item("warn", "D52 opt-out", f"agents may edit project config in {ws}")
        for ws in found.workspaces
    ]
    return items + [Item("warn", "D52 opt-out", f"not applied: {why}") for why in found.refused]


def _pending_pins(cwd: Path) -> list[Item]:
    from carter.config import load_config
    from carter.identity.pin import plan_pin
    from carter.identity.workspace import workspace_key

    carter_yaml = cwd / ".carter" / "carter.yaml"
    if not carter_yaml.is_file():
        return []
    try:
        identity = load_config(carter_yaml).get("identity") or {}
        plan = plan_pin(
            load_identity(), workspace_key(cwd),
            role=identity.get("role") or "", require_tier=identity.get("require_tier") or "",
        )  # fmt: skip
    except Exception as exc:  # a broken workspace file is not a host problem
        return [Item("info", "workspace", f"pinned policy not compared ({type(exc).__name__})")]
    if not plan.changes:
        return []
    names = ", ".join(c.field for c in plan.changes)
    return [
        Item(
            "warn",
            "workspace",
            f"carter.yaml and config.toml differ on: {names}",
            "Run `carter update`.",
        )
    ]


def _declined(state: GuardState) -> list[Item]:
    groups = {g.id: g.effect for g in consent_groups()}
    return [
        Item("info", "declined", f"{g}: not installed ({groups[g]})")
        for g in consent.declined_groups(state)
    ]


def _mcp_token(base_dir: Path | None) -> list[Item]:
    """Does the carter-github MCP entry read the PAT file? Names only, never the value."""
    data = _load_jsonc(config_target(base_dir)) if config_target(base_dir).exists() else None
    servers = ((data or {}).get("mcp") or {}).get("servers") or {}
    entry = servers.get("carter-github")
    if not isinstance(entry, dict):
        return []
    env = entry.get("environment") or entry.get("env") or {}
    value = env.get("GITHUB_PERSONAL_ACCESS_TOKEN") if isinstance(env, dict) else None
    if value == MCP_FILE_TOKEN:
        return [Item("ok", "mcp token", "carter-github reads the token from gh-read.token")]
    if isinstance(value, str) and value.startswith("{env:"):
        text = "carter-github still reads its token from an environment variable"
        return [Item("warn", "mcp token", text, "Run `carter install` to switch it to the file.")]
    if isinstance(value, str) and value:
        text = "carter-github has a literal token in the OpenCode config"
        return [Item("red", "mcp token", text, "Remove it and run `carter github-token set`.")]
    return [Item("warn", "mcp token", "carter-github has no token configured")]


def _token(base_dir: Path | None) -> list[Item]:
    return [*ghtoken.check_token(base_dir, required=False), *_mcp_token(base_dir)]


def _env(server_env: Mapping[str, str]) -> list[Item]:
    names = [n for n in load_rules().warn_only if n in server_env]
    if not names:
        return []
    return [
        Item("warn", "server env", f"{', '.join(names)} set in the server environment (names only)")
    ]


def run_host_checks(
    base_dir: Path | None = None,
    *,
    cwd: Path | None = None,
    reader: Reader | None = None,
    server_env: Mapping[str, str] | None = None,
    home: str | None = None,
) -> list[Item]:
    """All 1G host checks, in a stable order. Never raises for a failing check."""
    where = cwd or Path.cwd()
    items: list[Item] = []
    state_path = guard_state_path(base_dir)
    read = load_or_empty_readonly(state_path)

    def guarded(area: str, fn: Callable[[], list[Item]]) -> None:
        try:
            items.extend(fn())
        except Exception as exc:  # one broken check must not hide the others
            items.append(Item("red", area, f"check could not run ({type(exc).__name__})"))

    if read.status in ("corrupt", "newer"):
        text = f"{E_STATE_INVALID}: {state_path} is {read.status} ({read.detail})"
        items.append(Item("red", "guard state", text, STATE_HINT))
    elif read.status == "absent":
        items.append(
            Item("warn", "guard", "G2 off: no guards are installed", "Run `carter guard install`.")
        )
    else:
        state = read.state
        guarded("policies", lambda: _policies(state, reader, home or str(Path.home())))
        guarded("guard files", lambda: _files(state))
        guarded("consent", lambda: _declined(state))
        if "g2" in consent.accepted_groups(state):
            items.append(Item("warn", "plugin", PLUGIN_ABSENT))
        else:
            items.append(Item("warn", "guard", "G2 off: group g2 was not installed"))
    guarded("git", lambda: _git(read.state if read.status == "ok" else GuardState()))
    guarded("project", lambda: _project_scope(where))
    guarded("D52", _optouts)
    guarded("workspace", lambda: _pending_pins(where))
    guarded("token", lambda: _token(base_dir))
    items.append(
        Item(
            "info",
            "server env",
            "pollution (agent signals, isolation markers) not checked: slice 2a",
        )
    )
    items += _env(server_env or {})
    return items
