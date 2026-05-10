# /// script
# requires-python = ">=3.11"
# ///
"""Carter AI Assistant Installer.

Installs Carter agents, skills, instructions, knowledge base, and MCP server
configurations for VS Code Copilot, Copilot CLI, and OpenCode.

Usage:
    uv run install.py [OPTIONS]

Options:
    --target {copilot,opencode,all}   Install target (default: all)
    --uninstall                       Remove Carter installation
    --base-dir PATH                   Override install base directory (for testing)
    --quiet, -q                       Errors only
    --verbose, -v                     Detailed output
    --debug, -vv                      Debug output
    --help, -h                        Show this help
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# ANSI output helpers
# ──────────────────────────────────────────────────────────────────────────────

_NO_COLOR = not sys.stdout.isatty() or os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    if _NO_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(t: str) -> str:
    return _c("32", t)


def yellow(t: str) -> str:
    return _c("33", t)


def red(t: str) -> str:
    return _c("31", t)


def bold(t: str) -> str:
    return _c("1", t)


def dim(t: str) -> str:
    return _c("2", t)


# Log levels: 0=quiet, 1=default, 2=verbose, 3=debug
_verbosity = 1


def _log(msg: str, level: int = 1) -> None:
    if _verbosity >= level:
        print(msg)


def log_step(msg: str) -> None:
    _log(f"\n{bold('→')} {bold(msg)}")


def log_ok(msg: str, detail: str = "") -> None:
    suffix = f" {dim(detail)}" if detail else ""
    _log(f"  {green('✓')} {msg}{suffix}")


def log_warn(msg: str, hint: str = "") -> None:
    _log(f"  {yellow('⚠')} {msg}")
    if hint:
        _log(f"    {dim(hint)}")


def log_err(msg: str) -> None:
    _log(f"  {red('✗')} {msg}", level=0)


def log_skip(msg: str) -> None:
    _log(f"  {dim('·')} {msg}", level=2)


def log_debug(msg: str) -> None:
    _log(f"  {dim('[debug]')} {msg}", level=3)


# ──────────────────────────────────────────────────────────────────────────────
# Path resolution
# ──────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent


def _home() -> Path:
    return Path.home()


def _copilot_base(base_dir: Path | None) -> Path:
    if base_dir:
        return base_dir / "copilot"
    return _home() / ".copilot"


def _opencode_base(base_dir: Path | None) -> Path:
    if base_dir:
        return base_dir / "opencode"
    return _home() / ".config" / "opencode"


def _vscode_settings_path(base_dir: Path | None) -> Path:
    if base_dir:
        return base_dir / "vscode" / "settings.json"
    if platform.system() == "Darwin":
        return _home() / "Library" / "Application Support" / "Code" / "User" / "settings.json"
    return _home() / ".config" / "Code" / "User" / "settings.json"


# ──────────────────────────────────────────────────────────────────────────────
# JSONC parsing (JSON with Comments — used by VS Code settings.json)
# ──────────────────────────────────────────────────────────────────────────────


def _strip_jsonc(text: str) -> str:
    """Strip // and /* */ comments and trailing commas from JSONC text.

    Handles comments inside strings correctly (leaves them alone).
    """
    result: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        c = text[i]

        # String literal — copy verbatim, including any // or /* inside
        if c == '"':
            result.append(c)
            i += 1
            while i < n:
                sc = text[i]
                result.append(sc)
                if sc == '\\' and i + 1 < n:
                    i += 1
                    result.append(text[i])
                elif sc == '"':
                    break
                i += 1
            i += 1
            continue

        # Single-line comment
        if c == '/' and i + 1 < n and text[i + 1] == '/':
            # Skip to end of line
            i += 2
            while i < n and text[i] != '\n':
                i += 1
            continue

        # Block comment
        if c == '/' and i + 1 < n and text[i + 1] == '*':
            i += 2
            while i + 1 < n and not (text[i] == '*' and text[i + 1] == '/'):
                i += 1
            i += 2  # skip */
            continue

        result.append(c)
        i += 1

    # Remove trailing commas before } or ]
    import re
    cleaned = "".join(result)
    cleaned = re.sub(r',\s*([}\]])', r'\1', cleaned)
    return cleaned


def _load_jsonc(path: Path) -> dict | None:
    """Load a JSONC file (JSON with Comments). Returns None on failure."""
    try:
        raw = path.read_text()
        stripped = _strip_jsonc(raw)
        return json.loads(stripped)
    except (json.JSONDecodeError, OSError) as e:
        log_debug(f"JSONC parse failed for {path}: {e}")
        return None


def _write_json_preserving(path: Path, data: dict, original_text: str | None) -> None:
    """Write JSON data to a file.

    If the original file used JSONC features (comments, trailing commas),
    we cannot preserve those through a round-trip. We write clean JSON
    with the same indent style.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


# ──────────────────────────────────────────────────────────────────────────────
# File hashing
# ──────────────────────────────────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return f"sha256:{h.hexdigest()}"


# ──────────────────────────────────────────────────────────────────────────────
# Prerequisite checks
# ──────────────────────────────────────────────────────────────────────────────

REQUIRED_ENV_VARS = {
    "GITHUB_TOKEN": ("carter-github", True),
    "TF_TOKEN": ("carter-terraform", True),
    "ATLASSIAN_API_TOKEN": ("carter-atlassian", True),
    "ATLASSIAN_EMAIL": ("carter-atlassian", True),
    "ATLASSIAN_URL": ("carter-atlassian", True),
}


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _cmd_version(cmd: str, flag: str = "--version") -> str | None:
    try:
        result = subprocess.run(
            [cmd, flag], capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip().split("\n")[0] if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def detect_environment() -> dict:
    log_step("Detecting environment...")
    info = {
        "os": platform.system(),
        "os_version": platform.version().split()[0] if platform.version() else "unknown",
        "python": platform.python_version(),
    }
    uv_ver = _cmd_version("uv", "--version")
    info["uv"] = uv_ver.replace("uv ", "") if uv_ver else "not found"
    _log(f"  OS: {info['os']} | Python: {info['python']} | uv: {info['uv']}")
    return info


def check_prerequisites(targets: list[str]) -> dict[str, bool]:
    log_step("Checking prerequisites...")
    checks: dict[str, bool] = {}

    tools = [
        ("VS Code", "code", False),
        ("gh CLI", "gh", True),
        ("terraform", "terraform", True),
        ("jq", "jq", True),
    ]

    if "copilot" in targets:
        tools.append(("copilot CLI", "copilot", False))
    if "opencode" in targets:
        tools.append(("opencode", "opencode", False))

    for label, cmd, optional in tools:
        found = _which(cmd)
        version = _cmd_version(cmd, "--version") if found else None
        ver_str = version.split("\n")[0][:30] if version else ""

        if found:
            log_ok(label, ver_str)
            checks[cmd] = True
        elif optional:
            log_warn(f"{label} not found (optional)")
            checks[cmd] = False
        else:
            log_warn(f"{label} not found")
            checks[cmd] = False

    return checks


def check_credentials() -> dict[str, bool]:
    log_step("Checking credentials...")
    results: dict[str, bool] = {}

    for var, (server, required) in REQUIRED_ENV_VARS.items():
        val = os.environ.get(var)
        if val:
            log_ok(var)
            results[var] = True
        else:
            log_warn(var, f'export {var}="your-value"')
            results[var] = False

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Backup
# ──────────────────────────────────────────────────────────────────────────────


def _backup_file(path: Path, backup_root: Path) -> None:
    if not path.exists():
        return
    rel = path.name
    dest = backup_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    log_debug(f"Backed up {path} → {dest}")


# ──────────────────────────────────────────────────────────────────────────────
# File installation
# ──────────────────────────────────────────────────────────────────────────────


def _install_file(
    src: Path,
    dst: Path,
    manifest: dict,
    backup_root: Path,
) -> str:
    """Copy src to dst. Returns status: 'created', 'updated', or 'unchanged'."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_hash = _sha256(src)

    if dst.exists():
        dst_hash = _sha256(dst)
        if src_hash == dst_hash:
            log_skip(str(dst).replace(str(_home()), "~"))
            manifest["files"].append(str(dst))
            manifest["file_hashes"][str(dst)] = src_hash
            return "unchanged"
        _backup_file(dst, backup_root)
        shutil.copy2(src, dst)
        log_ok(f"{str(dst).replace(str(_home()), '~')}", "updated")
        manifest["files"].append(str(dst))
        manifest["file_hashes"][str(dst)] = src_hash
        return "updated"

    shutil.copy2(src, dst)
    log_ok(str(dst).replace(str(_home()), "~"))
    manifest["files"].append(str(dst))
    manifest["file_hashes"][str(dst)] = src_hash
    return "created"


# ──────────────────────────────────────────────────────────────────────────────
# Agent format translation (Copilot → OpenCode)
# ──────────────────────────────────────────────────────────────────────────────
# Both Copilot CLI and OpenCode use nearly identical formats.
# We store canonical files and copy to both locations as-is.
# ──────────────────────────────────────────────────────────────────────────────


def install_agents(
    targets: list[str],
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path,
) -> dict[str, int]:
    log_step("Installing agents...")
    src_dir = REPO_ROOT / "agents"
    stats: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0}

    for agent_file in sorted(src_dir.glob("carter-*.md")):
        if "copilot" in targets:
            dst = _copilot_base(base_dir) / "agents" / agent_file.name
            status = _install_file(agent_file, dst, manifest, backup_root)
            stats[status] += 1

        if "opencode" in targets:
            dst = _opencode_base(base_dir) / "agents" / agent_file.name
            status = _install_file(agent_file, dst, manifest, backup_root)
            stats[status] += 1

    return stats


def install_skills(
    targets: list[str],
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path,
) -> dict[str, int]:
    log_step("Installing skills...")
    src_dir = REPO_ROOT / "skills"
    stats: dict[str, int] = {"created": 0, "updated": 0, "unchanged": 0}

    for skill_dir in sorted(src_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            continue

        skill_files = [f for f in sorted(skill_dir.iterdir()) if f.is_file()]
        for src_file in skill_files:
            rel = src_file.relative_to(skill_dir)
            if "copilot" in targets:
                dst = _copilot_base(base_dir) / "skills" / skill_dir.name / rel
                status = _install_file(src_file, dst, manifest, backup_root)
                stats[status] += 1

            if "opencode" in targets:
                dst = _opencode_base(base_dir) / "skills" / skill_dir.name / rel
                status = _install_file(src_file, dst, manifest, backup_root)
                stats[status] += 1

    return stats


def install_instructions(
    targets: list[str],
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path,
) -> None:
    log_step("Installing instructions...")
    src = REPO_ROOT / "instructions" / "copilot-instructions.md"

    if "copilot" in targets:
        dst = _copilot_base(base_dir) / "instructions" / "copilot-instructions.md"
        _install_file(src, dst, manifest, backup_root)

    if "opencode" in targets:
        dst = _opencode_base(base_dir) / "instructions" / "copilot-instructions.md"
        _install_file(src, dst, manifest, backup_root)


def install_knowledge(
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path,
) -> int:
    log_step("Initializing knowledge base...")
    src_dir = REPO_ROOT / "knowledge"
    dst_dir = _copilot_base(base_dir) / "knowledge"
    count = 0

    for src_file in sorted(src_dir.glob("*.md")):
        dst = dst_dir / src_file.name
        if dst.exists():
            log_skip(f"{str(dst).replace(str(_home()), '~')} (exists, not overwriting)")
            manifest["files"].append(str(dst))
        else:
            _install_file(src_file, dst, manifest, backup_root)
            count += 1

    return count


# ──────────────────────────────────────────────────────────────────────────────
# MCP server configuration
# ──────────────────────────────────────────────────────────────────────────────


def _merge_json_key(file_path: Path, key: str, entries: dict, backup_root: Path | None = None) -> None:
    """Merge entries into a specific key of a JSON file.

    Handles JSONC (JSON with Comments) used by VS Code settings.json.
    Backs up the file before any modification.
    """
    data: dict = {}
    if file_path.exists():
        # Back up before modifying
        if backup_root:
            _backup_file(file_path, backup_root)

        data = _load_jsonc(file_path)
        if data is None:
            log_err(f"Could not parse {file_path} — skipping to avoid data loss")
            log_warn(
                "The file may contain syntax errors. Fix them and re-run the installer.",
                f"File: {file_path}",
            )
            return

    if key not in data:
        data[key] = {}

    # Check for non-carter conflicts
    for name in entries:
        base_name = name.replace("carter-", "")
        if base_name in data.get(key, {}) and name not in data.get(key, {}):
            log_warn(
                f'Existing "{base_name}" server found in {file_path.name}',
                f'Carter will install as "{name}" (separate entry). '
                f'You may want to remove "{base_name}" to avoid duplicate tools.',
            )

    data[key].update(entries)
    _write_json_preserving(file_path, data, None)


def configure_mcp_servers(
    targets: list[str],
    base_dir: Path | None,
    manifest: dict,
    prereqs: dict[str, bool],
    backup_root: Path | None = None,
) -> int:
    log_step("Configuring MCP servers...")
    count = 0
    servers = ["github", "terraform", "atlassian"]

    if "copilot" in targets:
        # VS Code settings.json
        vscode_settings = _vscode_settings_path(base_dir)
        copilot_entries = {}
        for server in servers:
            src = REPO_ROOT / "mcp" / "copilot" / f"{server}.json"
            copilot_entries.update(json.loads(src.read_text()))

        _merge_json_key(vscode_settings, "mcp.servers", copilot_entries, backup_root)
        for server in servers:
            log_ok(f"carter-{server} → VS Code settings.json")
            count += 1

        # Copilot CLI via `copilot mcp add`
        if prereqs.get("copilot", False) and not base_dir:
            for server in servers:
                src = REPO_ROOT / "mcp" / "copilot" / f"{server}.json"
                config = json.loads(src.read_text())
                name = f"carter-{server}"
                entry = config[name]

                cmd_parts = [entry["command"]] + entry.get("args", [])
                env_args = []
                for k, v in entry.get("env", {}).items():
                    env_val = os.environ.get(k, v)
                    env_args.extend(["--env", f"{k}={env_val}"])

                try:
                    # Remove first if exists (idempotent)
                    subprocess.run(
                        ["copilot", "mcp", "remove", name],
                        capture_output=True, timeout=10,
                    )
                    subprocess.run(
                        ["copilot", "mcp", "add", name] + env_args + ["--"] + cmd_parts,
                        capture_output=True, timeout=10, check=True,
                    )
                    log_ok(f"{name} → copilot mcp add")
                    count += 1
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                    log_warn(f"Failed to add {name} to Copilot CLI: {e}")
        elif not base_dir:
            log_skip("copilot CLI not found, skipping copilot mcp add")

    if "opencode" in targets:
        opencode_config = _opencode_base(base_dir) / "opencode.json"
        opencode_entries = {}
        for server in servers:
            src = REPO_ROOT / "mcp" / "opencode" / f"{server}.json"
            opencode_entries.update(json.loads(src.read_text()))

        _merge_json_key(opencode_config, "mcp", opencode_entries, backup_root)
        for server in servers:
            log_ok(f"carter-{server} → opencode.json")
            count += 1

    manifest["mcp_servers"] = [f"carter-{s}" for s in servers]
    return count


# ──────────────────────────────────────────────────────────────────────────────
# Manifest
# ──────────────────────────────────────────────────────────────────────────────


def write_manifest(manifest: dict, base_dir: Path | None) -> Path:
    manifest_path = _copilot_base(base_dir) / ".carter-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest_path


def read_manifest(base_dir: Path | None) -> dict | None:
    manifest_path = _copilot_base(base_dir) / ".carter-manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Uninstall
# ──────────────────────────────────────────────────────────────────────────────


def uninstall(targets: list[str], base_dir: Path | None, prereqs: dict[str, bool]) -> None:
    log_step("Uninstalling Carter...")
    manifest = read_manifest(base_dir)

    if manifest:
        # Remove files from manifest
        for f in manifest.get("files", []):
            p = Path(f)
            if p.exists():
                # Check if this file belongs to a requested target
                copilot_base = str(_copilot_base(base_dir))
                opencode_base = str(_opencode_base(base_dir))

                if "copilot" in targets and f.startswith(copilot_base):
                    p.unlink()
                    log_ok(f"Removed {f.replace(str(_home()), '~')}")
                elif "opencode" in targets and f.startswith(opencode_base):
                    p.unlink()
                    log_ok(f"Removed {f.replace(str(_home()), '~')}")
    else:
        # No manifest — remove by convention
        if "copilot" in targets:
            base = _copilot_base(base_dir)
            for pattern_dir in ["agents", "skills"]:
                d = base / pattern_dir
                if d.exists():
                    for f in d.glob("carter-*"):
                        if f.is_file():
                            f.unlink()
                            log_ok(f"Removed {str(f).replace(str(_home()), '~')}")
                        elif f.is_dir():
                            shutil.rmtree(f)
                            log_ok(f"Removed {str(f).replace(str(_home()), '~')}/")

        if "opencode" in targets:
            base = _opencode_base(base_dir)
            for pattern_dir in ["agents", "skills"]:
                d = base / pattern_dir
                if d.exists():
                    for f in d.glob("carter-*"):
                        if f.is_file():
                            f.unlink()
                            log_ok(f"Removed {str(f).replace(str(_home()), '~')}")
                        elif f.is_dir():
                            shutil.rmtree(f)
                            log_ok(f"Removed {str(f).replace(str(_home()), '~')}/")

    # Remove MCP server entries
    if "copilot" in targets:
        log_step("Removing MCP servers (VS Code)...")
        vscode_settings = _vscode_settings_path(base_dir)
        if vscode_settings.exists():
            data = _load_jsonc(vscode_settings)
            if data is not None:
                mcp = data.get("mcp.servers", {})
                removed = [k for k in list(mcp.keys()) if k.startswith("carter-")]
                for k in removed:
                    del mcp[k]
                    log_ok(f"Removed {k} from settings.json")
                data["mcp.servers"] = mcp
                _write_json_preserving(vscode_settings, data, None)
            else:
                log_err("Could not parse VS Code settings.json — skipping to avoid data loss")

        # Copilot CLI
        if prereqs.get("copilot", False) and not base_dir:
            log_step("Removing MCP servers (Copilot CLI)...")
            for server in ["github", "terraform", "atlassian"]:
                name = f"carter-{server}"
                try:
                    subprocess.run(
                        ["copilot", "mcp", "remove", name],
                        capture_output=True, timeout=10,
                    )
                    log_ok(f"Removed {name} from Copilot CLI")
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    log_skip(f"{name} not found in Copilot CLI")

    if "opencode" in targets:
        log_step("Removing MCP servers (OpenCode)...")
        opencode_config = _opencode_base(base_dir) / "opencode.json"
        if opencode_config.exists():
            data = _load_jsonc(opencode_config)
            if data is not None:
                mcp = data.get("mcp", {})
                removed = [k for k in list(mcp.keys()) if k.startswith("carter-")]
                for k in removed:
                    del mcp[k]
                    log_ok(f"Removed {k} from opencode.json")
                data["mcp"] = mcp
                _write_json_preserving(opencode_config, data, None)
            else:
                log_err("Could not parse opencode.json — skipping to avoid data loss")

    # Remove manifest
    manifest_path = _copilot_base(base_dir) / ".carter-manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
        log_ok("Removed manifest")

    _log(f"\n{green('✓')} {bold('Uninstall complete')}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Carter AI Assistant Installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--target",
        choices=["copilot", "opencode", "all"],
        default="all",
        help="Install target (default: all)",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove Carter installation",
    )
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=None,
        help="Override install base directory (for testing)",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Errors only",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Detailed output",
    )
    parser.add_argument(
        "-vv", "--debug",
        action="store_true",
        help="Debug output",
    )
    return parser.parse_args()


def main() -> None:
    global _verbosity
    args = parse_args()

    if args.quiet:
        _verbosity = 0
    elif args.debug:
        _verbosity = 3
    elif args.verbose:
        _verbosity = 2

    targets = ["copilot", "opencode"] if args.target == "all" else [args.target]

    _log(f"\n {bold('Carter Installer v1.0')}")
    _log(f" Target: {', '.join(targets)}")

    env = detect_environment()
    prereqs = check_prerequisites(targets)

    if args.uninstall:
        uninstall(targets, args.base_dir, prereqs)
        return

    creds = check_credentials()

    now = datetime.now(timezone.utc)
    backup_root = _copilot_base(args.base_dir) / "backup" / now.strftime("%Y%m%dT%H%M%S")

    manifest: dict = {
        "version": "1.0.0",
        "installed_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "targets": targets,
        "files": [],
        "mcp_servers": [],
        "file_hashes": {},
    }

    # Check for existing manifest (update scenario)
    existing = read_manifest(args.base_dir)
    if existing:
        manifest["installed_at"] = existing.get("installed_at", now.isoformat())
        log_debug("Existing installation found — updating")

    # Install components
    agent_stats = install_agents(targets, args.base_dir, manifest, backup_root)
    skill_stats = install_skills(targets, args.base_dir, manifest, backup_root)
    install_instructions(targets, args.base_dir, manifest, backup_root)
    knowledge_count = install_knowledge(args.base_dir, manifest, backup_root)
    mcp_count = configure_mcp_servers(targets, args.base_dir, manifest, prereqs, backup_root)

    # Write manifest
    manifest_path = write_manifest(manifest, args.base_dir)

    # Summary
    total_agents = agent_stats["created"] + agent_stats["updated"] + agent_stats["unchanged"]
    total_skills = skill_stats["created"] + skill_stats["updated"] + skill_stats["unchanged"]

    _log(f"\n{green('✓')} {bold('Installation complete')}")
    _log(f"  Agents: {total_agents}")
    _log(f"  Skills: {total_skills}")
    _log(f"  MCP servers: {mcp_count}")
    _log(f"  Knowledge files: {knowledge_count} new")
    _log(f"  Manifest: {str(manifest_path).replace(str(_home()), '~')}")

    # Show update stats if relevant
    updated = agent_stats["updated"] + skill_stats["updated"]
    unchanged = agent_stats["unchanged"] + skill_stats["unchanged"]
    if updated > 0 or unchanged > 0:
        _log(f"  Changes: {agent_stats['created'] + skill_stats['created']} created, "
             f"{updated} updated, {unchanged} unchanged", level=2)


if __name__ == "__main__":
    main()
