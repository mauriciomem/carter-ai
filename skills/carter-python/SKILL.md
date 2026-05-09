---
name: carter-python
description: Python coding standards, best practices, and enforcement checklist
argument-hint: "[Python code or project to review]"
---

<objective>
Enforce Python coding standards focused on maintainability, extensibility, testability, and security. This skill serves as both a reference guide and an active checklist for code review.
</objective>

<standards>

## Project Structure

Follow the `src` layout for packages:
```
project/
├── pyproject.toml          # Project metadata, dependencies, tool config
├── src/
│   └── package_name/
│       ├── __init__.py
│       ├── module.py
│       └── py.typed         # PEP 561 marker for type stubs
├── tests/
│   ├── conftest.py
│   ├── test_module.py
│   └── fixtures/
├── .python-version          # Pin Python version for uv
└── README.md
```

- Use `pyproject.toml` as the single source of project metadata (PEP 621).
- Use `uv` for dependency management and virtual environments.
- Pin dependencies with `uv lock`. Use `uv.lock` for reproducible builds.

**Source:** [PEP 621](https://peps.python.org/pep-0621/), [Python Packaging User Guide](https://packaging.python.org/)

## Design Patterns

### Prefer Composition Over Inheritance
```python
# Good: composition
class OrderProcessor:
    def __init__(self, validator: OrderValidator, notifier: Notifier):
        self._validator = validator
        self._notifier = notifier
```

### Use Dataclasses for Data Containers
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Config:
    host: str
    port: int = 8080
    debug: bool = False
```
Use `frozen=True` for immutable value objects. Use `@dataclass(slots=True)` for memory efficiency (Python 3.10+).

### Use Protocols for Structural Typing
```python
from typing import Protocol

class Repository(Protocol):
    def get(self, id: str) -> dict: ...
    def save(self, entity: dict) -> None: ...
```
Prefer `Protocol` over ABC when you want structural (duck) typing rather than nominal typing.

### Dependency Injection
Pass dependencies as constructor arguments. Don't import and instantiate inside methods.

### Registry Pattern for Extensibility
```python
_handlers: dict[str, type[Handler]] = {}

def register(name: str):
    def decorator(cls):
        _handlers[name] = cls
        return cls
    return decorator
```

**Source:** [PEP 544 – Protocols](https://peps.python.org/pep-0544/), [dataclasses docs](https://docs.python.org/3/library/dataclasses.html)

## Error Handling

### Custom Exception Hierarchy
```python
class AppError(Exception):
    """Base exception for the application."""

class ValidationError(AppError):
    """Input validation failed."""

class NotFoundError(AppError):
    """Requested resource not found."""
```

### Rules
- Catch specific exceptions, never bare `except:`.
- Use context managers (`with`) for resource cleanup.
- Add context when re-raising: `raise AppError("context") from original`.
- Don't use exceptions for control flow.
- Log at the boundary, not at every level.

**Source:** [Python docs — Errors and Exceptions](https://docs.python.org/3/tutorial/errors.html)

## Testing

- **Framework:** `pytest`
- **Fixtures:** Use `@pytest.fixture` for setup, `conftest.py` for shared fixtures.
- **Table-driven tests:**
  ```python
  @pytest.mark.parametrize("input,expected", [
      ("hello", "HELLO"),
      ("", ""),
      ("123", "123"),
  ])
  def test_to_upper(input, expected):
      assert to_upper(input) == expected
  ```
- **Mocking:** Use `unittest.mock.patch` to mock external dependencies. Don't mock what you own — use fakes or in-memory implementations instead.
- **Coverage:** Aim for meaningful coverage (80%+ for business logic). Don't chase 100% — test behavior, not implementation.

**Source:** [pytest docs](https://docs.pytest.org/), [unittest.mock docs](https://docs.python.org/3/library/unittest.mock.html)

## Security

- **Input validation:** Validate all external input at system boundaries using `pydantic` or manual validation.
- **Secrets:** Never hardcode. Use environment variables or secret managers.
- **Dependencies:** Scan with `pip-audit` or `uv audit` regularly.
- **Static analysis:** Run `bandit` for security-focused linting.
- **SQL injection:** Use parameterized queries. Never string-format SQL.
- **Serialization:** Never `pickle.loads()` untrusted data. Prefer JSON.
- **File paths:** Validate and sanitize. Prevent path traversal.

**Source:** [OWASP Python Security](https://cheatsheetseries.owasp.org/cheatsheets/Python_Security_Cheat_Sheet.html), [bandit docs](https://bandit.readthedocs.io/)

## Code Quality

- **Formatter/Linter:** `ruff` (replaces black, isort, flake8, and more).
  ```toml
  [tool.ruff]
  target-version = "py311"
  line-length = 88
  ```
- **Type checking:** `mypy` with strict mode.
  ```toml
  [tool.mypy]
  strict = true
  ```
- **Type hints:** Required on all public functions and methods. Use `from __future__ import annotations` for modern syntax.
- **Docstrings:** Google style for public APIs:
  ```python
  def process(items: list[str], limit: int = 10) -> list[str]:
      """Process items up to the given limit.

      Args:
          items: The items to process.
          limit: Maximum number of items to return.

      Returns:
          Processed items, truncated to limit.

      Raises:
          ValidationError: If items is empty.
      """
  ```

**Source:** [PEP 8](https://peps.python.org/pep-0008/), [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html), [ruff docs](https://docs.astral.sh/ruff/)

## Concurrency

- **asyncio:** Use for I/O-bound concurrency (HTTP clients, database queries).
- **concurrent.futures:** Use `ThreadPoolExecutor` for blocking I/O, `ProcessPoolExecutor` for CPU-bound work.
- **Rules:**
  - Don't mix sync and async without `asyncio.to_thread()`.
  - Use `asyncio.TaskGroup` (Python 3.11+) for structured concurrency.
  - Always handle cancellation properly.
  - Use `asyncio.Lock` for shared mutable state in async code.

**Source:** [asyncio docs](https://docs.python.org/3/library/asyncio.html)

## Dependency Management

- **Tool:** `uv` (fast, reliable, replaces pip, pip-tools, virtualenv).
- **Lock file:** Always commit `uv.lock` for reproducible builds.
- **Minimal dependencies:** Only add what you need. Evaluate before adding.
- **Version constraints:** Use `>=` with upper bounds sparingly. Let the resolver handle conflicts.

**Source:** [uv docs](https://docs.astral.sh/uv/)

</standards>

<checklist>

## Enforcement Checklist

When reviewing Python code, verify each item:

- [ ] Project uses `pyproject.toml` (not `setup.py` or `setup.cfg`)
- [ ] Dependencies managed with `uv`, `uv.lock` committed
- [ ] Type hints on all public functions
- [ ] `ruff` passes (format + lint)
- [ ] `mypy` passes (strict mode)
- [ ] Custom exception hierarchy (no bare `except:`)
- [ ] Tests exist and use pytest
- [ ] No hardcoded secrets
- [ ] `bandit` or equivalent security scan passes
- [ ] Input validation at system boundaries
- [ ] Dataclasses or Pydantic for data structures (not plain dicts for domain objects)
- [ ] Dependencies are minimal and scanned (`pip-audit` or `uv audit`)

</checklist>
