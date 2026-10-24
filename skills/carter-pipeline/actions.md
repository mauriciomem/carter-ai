# GitHub Actions Pipelines

Design and create GitHub Actions workflows for CI/CD.

## Design Principles

1. **Fast feedback** — run fast checks first (lint, format) before slow ones (build, test, deploy)
2. **Fail fast** — stop the pipeline on first failure
3. **Reproducible** — pin action versions with SHA hashes, pin dependency versions
4. **Secure** — never echo secrets, minimize permissions with `permissions:` key
5. **Cacheable** — cache dependencies, build artifacts, and Docker layers

> **Pinning note:** examples below use readable major tags (`@v7`) for brevity. In real
> workflows pin the full commit SHA with an exact-version comment, as in the first
> `checkout` step — e.g. `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`.
> Resolve annotated tags to the commit SHA (`gh api repos/OWNER/REPO/git/ref/tags/vX.Y.Z`,
> then follow `object.type == "tag"`). Let Dependabot/Renovate keep pins current.
> Versions current as of 2026-10.

## Workflow Structure

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
      - name: Lint
        run: echo "lint step"

  test:
    needs: lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Test
        run: echo "test step"

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Build
        run: echo "build step"

  deploy:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Deploy
        run: echo "deploy step"
```

## Triggers

```yaml
# PR and push
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

# Path filters — only run when relevant files change
on:
  push:
    paths:
      - 'src/**'
      - 'tests/**'
    paths-ignore:
      - '**.md'
      - 'docs/**'

# Scheduled
on:
  schedule:
    - cron: '0 6 * * 1'  # Monday 6am UTC

# Manual dispatch
on:
  workflow_dispatch:
    inputs:
      environment:
        type: choice
        options: [staging, production]
```

## Language-Specific Patterns

### Python

```yaml
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
      - name: Lint
        run: uv run --with ruff ruff check .
      - name: Test
        run: uv run --with pytest pytest tests/ -v
```

Cache: `~/.cache/uv`

### Go

```yaml
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-go@v7
        with:
          go-version-file: go.mod
      - run: go vet ./...
      - run: golangci-lint run
      - run: go test ./...
```

Cache: `~/go/pkg/mod`, `~/.cache/go-build`

### Terraform

```yaml
jobs:
  terraform:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v7
      - uses: hashicorp/setup-terraform@v4
      - run: terraform fmt -check
      - run: terraform init
      - run: terraform validate
      - run: terraform plan -no-color
```

### Node.js

```yaml
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with:
          node-version-file: .nvmrc
          cache: npm
      - run: npm ci
      - run: npm run lint
      - run: npm test
```

## Caching

```yaml
- uses: actions/cache@v6
  with:
    path: |
      ~/.cache/uv
      ~/.cache/pip
    key: ${{ runner.os }}-deps-${{ hashFiles('**/pyproject.toml') }}
    restore-keys: |
      ${{ runner.os }}-deps-
```

## Secrets and Environment Variables

```yaml
env:
  APP_ENV: production

jobs:
  deploy:
    environment: production
    steps:
      - name: Deploy
        env:
          API_KEY: ${{ secrets.API_KEY }}
        run: ./deploy.sh
```

- Use `${{ secrets.NAME }}`, never echo secrets
- Use **environments** for deployment protection rules (approvals, wait timers)
- Prefer **OIDC** for cloud authentication over long-lived credentials

## Matrix Builds

```yaml
jobs:
  test:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
        python-version: ['3.11', '3.14', '3.15']
      fail-fast: true
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pytest
```

## Artifacts

```yaml
# Upload
- uses: actions/upload-artifact@v7
  with:
    name: build-output
    path: dist/

# Download (in a later job)
- uses: actions/download-artifact@v8
  with:
    name: build-output
```

## Reusable Workflows

```yaml
# .github/workflows/reusable-test.yml
on:
  workflow_call:
    inputs:
      python-version:
        type: string
        default: '3.14'

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: ${{ inputs.python-version }}
      - run: pytest
```

```yaml
# .github/workflows/ci.yml
jobs:
  test:
    uses: ./.github/workflows/reusable-test.yml
    with:
      python-version: '3.14'
```

## Security Checklist

- [ ] `permissions:` block is minimal (not using defaults)
- [ ] Actions pinned by SHA, not tag (`uses: actions/checkout@<sha>`)
- [ ] Secrets used via `${{ secrets.NAME }}`, never echoed
- [ ] No `pull_request_target` without careful review
- [ ] OIDC for cloud authentication where possible
- [ ] Third-party actions reviewed before use
- [ ] `fail-fast: true` on matrix builds to save compute
