# Terraform Testing Framework

Write comprehensive Terraform tests using the built-in testing framework (.tftest.hcl) to validate configuration behavior, variable validation rules, and module outputs.

## Core Concepts

- **Test file** (`.tftest.hcl`): contains `run` blocks that validate your configuration
- **Run block**: a single test scenario with optional variables, providers, and assertions
- **Assert block**: conditions that must be true for the test to pass
- **Mock provider**: simulates provider behavior without real infrastructure (Terraform 1.7+)
- **Test modes**: `apply` (default, creates real resources) or `plan` (validates logic only)

## File Structure

```
my-module/
├── main.tf
├── variables.tf
├── outputs.tf
└── tests/
    ├── defaults_unit_test.tftest.hcl         # plan mode — fast, no real resources
    ├── validation_unit_test.tftest.hcl        # plan mode
    └── full_stack_integration_test.tftest.hcl # apply mode — creates real resources
```

Use `*_unit_test.tftest.hcl` for plan-mode tests and `*_integration_test.tftest.hcl` for apply-mode tests so they can be filtered separately in CI.

## Test File Structure

```hcl
# Optional: file-level variables (highest precedence, override all other sources)
variables {
  aws_region    = "us-west-2"
  instance_type = "t2.micro"
}

# Optional: provider configuration
provider "aws" {
  region = var.aws_region
}

# Required: at least one run block
run "test_default_configuration" {
  command = plan  # or apply (default)

  assert {
    condition     = aws_instance.example.instance_type == "t2.micro"
    error_message = "Instance type should be t2.micro by default"
  }
}
```

## Run Block

```hcl
run "test_name" {
  command  = plan  # or apply (default)
  parallel = true  # optional, since v1.9.0

  # Override file-level variables
  variables {
    instance_type = "t3.large"
  }

  # Reference a specific module
  module {
    source  = "./modules/vpc"  # local or registry only (not git/http)
    version = "5.0.0"          # registry modules only
  }

  # Control state isolation
  state_key = "shared_state"  # since v1.9.0

  # Plan behavior
  plan_options {
    mode    = refresh-only  # or normal (default)
    refresh = true
    replace = [aws_instance.example]
    target  = [aws_instance.example]
  }

  # Assertions
  assert {
    condition     = aws_instance.example.id != ""
    error_message = "Instance should have a valid ID"
  }

  # Expected failures (test passes if these fail)
  expect_failures = [
    var.instance_count
  ]
}
```

## Common Test Patterns

### Validate outputs

```hcl
run "test_outputs" {
  command = plan

  assert {
    condition     = output.vpc_id != null
    error_message = "VPC ID output must be defined"
  }

  assert {
    condition     = can(regex("^vpc-", output.vpc_id))
    error_message = "VPC ID should start with 'vpc-'"
  }
}
```

### Conditional resources

```hcl
run "test_nat_gateway_disabled" {
  command = plan

  variables {
    create_nat_gateway = false
  }

  assert {
    condition     = length(aws_nat_gateway.main) == 0
    error_message = "NAT gateway should not be created when disabled"
  }
}
```

### Resource counts

```hcl
run "test_resource_count" {
  command = plan

  variables {
    instance_count = 3
  }

  assert {
    condition     = length(aws_instance.workers) == 3
    error_message = "Should create exactly 3 worker instances"
  }
}
```

### Tags

```hcl
run "test_resource_tags" {
  command = plan

  variables {
    common_tags = {
      Environment = "production"
      ManagedBy   = "Terraform"
    }
  }

  assert {
    condition     = aws_instance.example.tags["Environment"] == "production"
    error_message = "Environment tag should be set correctly"
  }
}
```

### Validation rules (negative tests)

```hcl
run "test_invalid_environment" {
  command = plan

  variables {
    environment = "invalid"
  }

  expect_failures = [
    var.environment
  ]
}
```

### Sequential tests with dependencies

```hcl
run "setup_vpc" {
  command = apply

  assert {
    condition     = output.vpc_id != ""
    error_message = "VPC should be created"
  }
}

run "test_subnet_in_vpc" {
  command = plan

  variables {
    vpc_id = run.setup_vpc.vpc_id
  }

  assert {
    condition     = aws_subnet.example.vpc_id == run.setup_vpc.vpc_id
    error_message = "Subnet should be in the VPC from setup_vpc"
  }
}
```

### Complex conditions

```hcl
assert {
  condition = alltrue([
    for subnet in aws_subnet.private :
    can(regex("^10\\.0\\.", subnet.cidr_block))
  ])
  error_message = "All private subnets should use 10.0.0.0/8 CIDR range"
}
```

### State key sharing

```hcl
run "create_foundation" {
  command   = apply
  state_key = "foundation"

  assert {
    condition     = aws_vpc.main.id != ""
    error_message = "Foundation VPC should be created"
  }
}

run "create_application" {
  command   = apply
  state_key = "foundation"

  variables {
    vpc_id = run.create_foundation.vpc_id
  }

  assert {
    condition     = aws_instance.app.vpc_id == run.create_foundation.vpc_id
    error_message = "Application should use foundation VPC"
  }
}
```

### Multiple aliased providers

```hcl
provider "aws" {
  alias  = "secondary"
  region = "us-east-1"
}

run "test_with_specific_provider" {
  command = plan

  providers = {
    aws = provider.aws.secondary
  }

  assert {
    condition     = aws_instance.example.availability_zone == "us-east-1a"
    error_message = "Instance should be in us-east-1 region"
  }
}
```

## Cleanup

Resources are destroyed in **reverse run block order** after test completion. This matters for dependencies (e.g., S3 objects before bucket). Use `terraform test -no-cleanup` to skip cleanup for debugging.

## Running Tests

```bash
terraform test                                    # all tests
terraform test tests/defaults.tftest.hcl          # specific file
terraform test -filter=test_vpc_configuration     # by run block name
terraform test -test-directory=integration-tests  # custom directory
terraform test -verbose                           # detailed output
terraform test -no-cleanup                        # skip resource cleanup
```

## Best Practices

1. **Default to plan mode** — use `command = plan` unless you need to test real resource behavior
2. **Use mocks** for external dependencies (Terraform 1.7+) — faster, no credentials needed
3. **Error messages** — make them specific enough to diagnose failures without rerunning
4. **Negative tests** — use `expect_failures` to verify validation rules reject bad inputs
5. **Variable coverage** — test different variable combinations to validate all code paths
6. **Module sources** — test files only support local paths and registry modules (not git/http)
7. **Parallel execution** — use `parallel = true` for independent tests with different state files
8. **CI/CD** — run unit tests on every PR, integration tests on merge

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Assertion failures | Use `-verbose` to see actual vs expected values |
| Missing credentials | Use mock providers for unit tests |
| Unsupported module source | Convert git/HTTP sources to local modules |
| Tests interfering | Use `state_key` or separate modules for isolation |
| Slow tests | Use `command = plan` and mocks; run integration tests separately |
