# Security policy

## Supported versions

Only the latest minor release of Carter (`0.x`) gets security fixes. Upgrade with
`uv tool upgrade carter-ai`; there are no backports to older minors.

## Reporting a vulnerability

Please report it privately, not in a public issue or pull request:

1. Open the [Security tab](https://github.com/mauriciomem/carter-ai/security) of the repository.
2. Choose **Report a vulnerability** and describe the problem.

Useful details: the Carter version (`carter --version`), your OS, OpenCode and git versions, the
steps to reproduce, and what an attacker would gain. Do not include real secrets or tokens.

What to expect:

- An acknowledgement, which we aim to send within a week.
- A first assessment (accepted, needs more information, or out of scope) after that.
- A fix in a new release for accepted reports, and a published advisory that credits you unless
  you prefer not to be named.
- Please keep the report private until the fix is released.

In scope: Carter's CLI, the guards (gate, hooks, plugin, `carter_push`), the installer and
uninstaller, the agent and skill templates, and the release pipeline. Out of scope: bugs in
OpenCode, git, uv or a model provider themselves, and the documented limits listed in
[Safety and permissions](docs/guides/safety-and-permissions.md#what-the-guards-cannot-do).

## Verifying a release

Carter is published to PyPI only by this repository's release workflow, using
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (no long-lived upload token), and
the files carry [PEP 740](https://peps.python.org/pep-0740/) attestations.

| Item | Expected value |
|------|----------------|
| PyPI project | `carter-ai` |
| Source repository | `mauriciomem/carter-ai` |
| Publishing workflow | `release.yml` |
| GitHub environment | `pypi` (each publication needs a maintainer's approval) |
| GitHub Releases | Created by the same workflow |

Check a wheel:

```bash
uvx pypi-attestations verify pypi \
  --repository https://github.com/mauriciomem/carter-ai \
  pypi:carter_ai-X.Y.Z-py3-none-any.whl
```

If a release on PyPI has no attestation, or names another repository or workflow, do not use it
and report it as described above. uv and pip do not check attestations when installing, so
pinning a version (`uv tool install carter-ai==X.Y.Z`) and verifying are your choice to make.
