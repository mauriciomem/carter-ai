---
name: carter-pipeline
description: Create and modify GitHub Actions workflows for CI/CD pipelines
argument-hint: "[pipeline type or repo to set up CI/CD for]"
---

<objective>
Design, create, and modify GitHub Actions workflows following best practices for CI/CD pipelines.
</objective>

<guidelines>

## Pipeline Design Principles

1. **Fast feedback** — Run fast checks first (lint, format) before slow ones (build, test, deploy).
2. **Fail fast** — Stop the pipeline on first failure. Don't waste compute on doomed runs.
3. **Reproducible** — Pin action versions with SHA hashes, pin dependency versions.
4. **Secure** — Never echo secrets. Use GitHub's secret management. Minimize permissions with `permissions:` key.
5. **Cacheable** — Cache dependencies, build artifacts, and Docker layers.

## Workflow Structure

```yaml
name: [Descriptive Name]

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read  # Minimum required permissions

jobs:
  lint:
    # Fast checks first
  test:
    # Unit + integration tests
    needs: lint
  build:
    # Build artifacts
    needs: test
  deploy:
    # Deploy (only on main, with environment protection)
    needs: build
    if: github.ref == 'refs/heads/main'
```

## Language-Specific Patterns

### Python
- Use `uv` for dependency installation and test running
- Lint with `ruff`, type-check with `mypy`
- Test with `pytest` and coverage reporting
- Cache `~/.cache/uv`

### Go
- Use `go build`, `go test`, `go vet`
- Lint with `golangci-lint`
- Cache `~/go/pkg/mod` and `~/.cache/go-build`

### Terraform
- `terraform fmt -check` → `terraform validate` → `terraform plan`
- Use `hashicorp/setup-terraform` action
- Store plan output as PR comment

## Security Checklist
- [ ] `permissions:` block is minimal (not using defaults)
- [ ] Actions pinned by SHA, not tag
- [ ] Secrets used via `${{ secrets.NAME }}`, never echoed
- [ ] No `pull_request_target` without careful review
- [ ] OIDC for cloud authentication where possible (no long-lived credentials)

</guidelines>
