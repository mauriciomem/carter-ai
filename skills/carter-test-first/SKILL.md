---
name: carter-test-first
description: Generate tests before implementation following TDD workflow
argument-hint: "[feature or function to test]"
---

<objective>
Implement Test-Driven Development: write tests first, then guide implementation to make them pass. Ensure tests are meaningful, maintainable, and cover the right scenarios.
</objective>

<workflow>

## TDD Workflow

1. **Understand** — Read the requirement or feature description. Ask clarifying questions if the expected behavior is ambiguous.

2. **Design test cases** — Before writing any test code, list the scenarios:
   - Happy path(s)
   - Edge cases (empty input, boundary values, nil/None)
   - Error cases (invalid input, network failure, permission denied)
   - Integration points (if applicable)

3. **Write tests** — Implement the test cases:
   - Python: pytest with fixtures, parametrize for table-driven tests
   - Go: `testing` package with subtests, table-driven tests

4. **Verify tests fail** — Run the tests to confirm they fail for the right reason (test the test).

5. **Guide implementation** — Help implement the minimum code to make tests pass.

6. **Refactor** — Once tests pass, suggest refactoring opportunities while keeping tests green.

</workflow>

<test-quality>

## What Makes a Good Test

- **Descriptive name** — Test name describes the scenario, not the implementation: `test_returns_empty_list_when_no_items_match` not `test_filter`
- **Arrange-Act-Assert** — Clear structure: set up, execute, verify
- **One assertion per concept** — Each test verifies one behavior
- **Independent** — Tests don't depend on each other's state or execution order
- **Fast** — Unit tests should run in milliseconds
- **Deterministic** — No flaky tests. Mock external dependencies.

## Python Conventions
- Use `pytest` (not `unittest`)
- Use `@pytest.fixture` for setup/teardown
- Use `@pytest.mark.parametrize` for table-driven tests
- Use `unittest.mock.patch` for mocking
- Place tests in `tests/` mirroring the source structure

## Go Conventions
- Use `testing.T` with subtests (`t.Run`)
- Table-driven tests with `[]struct{ name string; ... }`
- Use `testify/assert` or `testify/require` for assertions
- Place tests in `_test.go` files alongside source
- Use `t.Helper()` in test helper functions

</test-quality>
