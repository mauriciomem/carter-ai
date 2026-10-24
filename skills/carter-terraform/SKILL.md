---
name: carter-terraform
description: Write and review Terraform configurations following HashiCorp best practices. Covers HCL style, modules, testing, import/search, and Stacks.
argument-hint: "[infrastructure component or Terraform config to review]"
---

<objective>
Write, review, and troubleshoot Terraform configurations following HashiCorp best practices and security standards.
</objective>

<routing>

## Specialized References

This file covers core Terraform conventions. For specialized topics, use `read_file` to load the appropriate reference from the **same directory** as this SKILL.md before proceeding.

| File | Load when the request involves |
|------|-------------------------------|
| `testing.md` | `.tftest.hcl`, run blocks, assertions, test patterns, expect_failures, mock providers, terraform test |
| `modules.md` | module extraction, refactoring, moved blocks, state migration, module interface design, composition |
| `import.md` | importing resources, `.tfquery.hcl`, terraform query, bulk import, unmanaged infrastructure, terraform search |
| `stacks.md` | Terraform Stacks, `.tfcomponent.hcl`, `.tfdeploy.hcl`, deployments, workload identity, multi-environment orchestration |

**How to load:** derive the directory path from this SKILL.md's location and read the sibling file. For example, if this file is at `~/.copilot/skills/carter-terraform/SKILL.md`, read `~/.copilot/skills/carter-terraform/testing.md`.

If the request does not match any specialized topic, use the core guidelines below without loading additional files.

</routing>

<guidelines>

## Code Generation Strategy

When generating Terraform code:

1. Start with provider configuration and version constraints
2. Create data sources before dependent resources
3. Build resources in dependency order
4. Add outputs for key resource attributes
5. Use variables for all configurable values

## File Organization

| File | Purpose |
|------|---------|
| `terraform.tf` | Terraform and provider version requirements |
| `providers.tf` | Provider configurations |
| `main.tf` | Primary resources and data sources |
| `variables.tf` | Input variable declarations (alphabetical) |
| `outputs.tf` | Output value declarations (alphabetical) |
| `locals.tf` | Local value declarations |

```hcl
# terraform.tf
terraform {
  required_version = ">= 1.14" # 1.14+ for list resources/query; latest is 1.17 (2026-10)

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
```

Use the latest major version of each provider and the latest minor version of Terraform, unless constrained by a dependency lock file or other modules.

### Module Structure

```
modules/<module>/
├── main.tf
├── variables.tf
├── outputs.tf
├── README.md
└── tests/
    ├── defaults_unit_test.tftest.hcl
    └── full_stack_integration_test.tftest.hcl
```

Module naming: `terraform-<provider>-<name>`

## Code Formatting

- Use **two spaces** per nesting level (no tabs)
- Align equals signs for consecutive arguments
- Arguments precede blocks, with meta-arguments first
- Lifecycle blocks go last

```hcl
resource "aws_instance" "example" {
  # Meta-arguments first
  count = 3

  # Arguments
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t2.micro"

  # Blocks
  root_block_device {
    volume_size = 20
  }

  # Lifecycle last
  lifecycle {
    create_before_destroy = true
  }
}
```

## Naming Conventions

- Use **lowercase with underscores** for all names
- Use **descriptive nouns** excluding the resource type
- Resource names must be singular, not plural
- Default to `main` when only one instance exists

```hcl
# Bad
resource "aws_instance" "webAPI-aws-instance" {}
resource "aws_instance" "web_apis" {}

# Good
resource "aws_instance" "web_api" {}
resource "aws_vpc" "main" {}
```

## Variables

Every variable must include `type` and `description`:

```hcl
variable "instance_type" {
  description = "EC2 instance type for the web server"
  type        = string
  default     = "t2.micro"

  validation {
    condition     = contains(["t2.micro", "t2.small", "t2.medium"], var.instance_type)
    error_message = "Instance type must be t2.micro, t2.small, or t2.medium."
  }
}

variable "database_password" {
  description = "Password for the database admin user"
  type        = string
  sensitive   = true
}
```

- Use `default` only when a sensible default exists
- Use `sensitive = true` for secrets
- Group related variables logically

## Outputs

Every output must include `description`:

```hcl
output "instance_id" {
  description = "ID of the EC2 instance"
  value       = aws_instance.web.id
}
```

## Dynamic Resource Creation

Prefer `for_each` over `count` for named resources. Use `count` only for conditional creation:

```hcl
# for_each for named instances
resource "aws_instance" "web" {
  for_each = var.instance_names
  tags     = { Name = each.key }
}

# count for conditional creation
resource "aws_cloudwatch_metric_alarm" "cpu" {
  count      = var.enable_monitoring ? 1 : 0
  alarm_name = "high-cpu-usage"
  threshold  = 80
}
```

## Provider Configuration

```hcl
provider "aws" {
  region = "us-west-2"

  default_tags {
    tags = {
      ManagedBy = "Terraform"
      Project   = var.project_name
    }
  }
}

# Aliased provider for multi-region
provider "aws" {
  alias  = "east"
  region = "us-east-1"
}
```

## State Management

- Always use remote state (S3 + DynamoDB, Terraform Cloud, etc.)
- Enable state locking
- Never commit `.tfstate` files
- Use workspaces or directory-based separation for environments

## Security

- Never hardcode secrets — use variables, Vault, or environment variables
- Use `sensitive = true` for secret variables and outputs
- Pin provider versions
- Enable encryption at rest and in transit for all storage resources
- Use IAM least-privilege policies
- Review `terraform plan` output carefully before `apply`

## Version Control

**Never commit:** `terraform.tfstate`, `.terraform/`, `*.tfplan`, `.tfvars` with secrets

**Always commit:** all `.tf` files, `.terraform.lock.hcl`

**Version constraint operators:**
- `= 1.0.0` — Exact version
- `>= 1.0.0` — Greater than or equal
- `~> 1.0` — Allow rightmost component to increment
- `>= 1.0, < 2.0` — Version range

</guidelines>

<review-checklist>

## Terraform Review Checklist

### Code Quality
- [ ] Code formatted with `terraform fmt`
- [ ] Configuration validated with `terraform validate`
- [ ] Files organized according to standard structure
- [ ] Resource names use descriptive nouns with underscores

### Variables and Outputs
- [ ] All variables have `type` and `description`
- [ ] All outputs have `description`
- [ ] Validation blocks for input constraints where appropriate
- [ ] Sensitive values marked with `sensitive = true`

### Security
- [ ] No hardcoded secrets or credentials
- [ ] Provider versions pinned explicitly
- [ ] Remote state configured with locking
- [ ] Security groups follow least-privilege
- [ ] Encryption enabled for storage and transit

### Infrastructure
- [ ] Tags applied consistently (at minimum: Name, Environment, ManagedBy)
- [ ] `for_each` preferred over `count` for named resources
- [ ] `.terraform.lock.hcl` committed to version control

### Validation Tools

```bash
terraform fmt -recursive
terraform validate
```

Additional tools: `tflint` (linting), `trivy config` / `checkov` (security scanning; `tfsec` is deprecated and merged into Trivy)

</review-checklist>
