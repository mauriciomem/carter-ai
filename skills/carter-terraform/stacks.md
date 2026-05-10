# Terraform Stacks

Create and manage Terraform Stack configurations for orchestrating multi-component, multi-environment infrastructure on HCP Terraform.

## Core Concepts

- **Stack**: a complete unit of infrastructure composed of components and deployments
- **Component** (`.tfcomponent.hcl`): abstraction around a Terraform module with inputs and providers
- **Deployment** (`.tfdeploy.hcl`): an instance of all components with specific input values (per environment/region)
- **Stack Language**: a separate HCL-based language (not regular Terraform HCL)

## File Structure

```
my-stack/
├── .terraform-version               # Required Terraform version (e.g., 1.14.5)
├── variables.tfcomponent.hcl        # Variable declarations
├── providers.tfcomponent.hcl        # Provider configurations
├── components.tfcomponent.hcl       # Component definitions
├── outputs.tfcomponent.hcl          # Stack outputs
├── deployments.tfdeploy.hcl         # Deployment definitions
├── .terraform.lock.hcl              # Provider lock file (generated)
└── modules/                         # Local modules (optional)
```

All configuration files must be at the root level. HCP Terraform processes all files in dependency order.

## Component Configuration (.tfcomponent.hcl)

### Variable Block

Variables must define `type`. Do not support `validation`.

```hcl
variable "aws_region" {
  type        = string
  description = "AWS region for deployments"
  default     = "us-west-1"
}

variable "identity_token" {
  type        = string
  description = "OIDC identity token"
  ephemeral   = true  # Does not persist to state file
}

variable "instance_count" {
  type     = number
  nullable = false
}
```

Use `ephemeral = true` for credentials and tokens to prevent them from persisting in state files.

### Required Providers Block

```hcl
required_providers {
  aws = {
    source  = "hashicorp/aws"
    version = "~> 6.0"
  }
}
```

### Provider Block

Provider blocks in Stacks differ from traditional Terraform — they support `for_each`, define aliases in the block header, and accept config through a `config` block:

```hcl
# Single provider
provider "aws" "this" {
  config {
    region = var.aws_region
    assume_role_with_web_identity {
      role_arn           = var.role_arn
      web_identity_token = var.identity_token
    }
  }
}

# Multiple providers with for_each
provider "aws" "configurations" {
  for_each = var.regions

  config {
    region = each.value
    assume_role_with_web_identity {
      role_arn           = var.role_arn
      web_identity_token = var.identity_token
    }
  }
}
```

**Authentication**: prefer **workload identity** (OIDC) over static credentials. Use `identity_token` blocks with `assume_role_with_web_identity`.

### Component Block

Each Stack requires at least one component. Components reference modules from local paths, registries, or Git:

```hcl
component "vpc" {
  source  = "app.terraform.io/my-org/vpc/aws"
  version = "2.1.0"

  inputs = {
    cidr_block  = var.vpc_cidr
    name_prefix = var.name_prefix
  }

  providers = {
    aws = provider.aws.this
  }
}

component "application" {
  source = "./modules/app"

  inputs = {
    vpc_id     = component.vpc.vpc_id         # dependency inferred
    subnet_ids = component.vpc.private_subnet_ids
  }

  providers = {
    aws = provider.aws.this
  }
}
```

**Key points:**
- Reference outputs: `component.<name>.<output>` or `component.<name>[key].<output>` for `for_each`
- Dependencies inferred automatically from component references
- Modules used with Stacks **cannot include provider blocks**

### Output Block

Outputs require a `type` argument:

```hcl
output "vpc_id" {
  type        = string
  description = "VPC ID"
  value       = component.vpc.vpc_id
}

output "endpoint_urls" {
  type  = map(string)
  value = {
    for region, comp in component.api : region => comp.endpoint_url
  }
}
```

### Removed Block

Safely remove components from a Stack:

```hcl
removed {
  from   = component.old_component
  source = "./modules/old-module"

  providers = {
    aws = provider.aws.this
  }
}
```

## Deployment Configuration (.tfdeploy.hcl)

### Identity Token Block

Generate JWT tokens for OIDC authentication:

```hcl
identity_token "aws" {
  audience = ["aws.workload.identity"]
}
```

Reference in deployments: `identity_token.<name>.jwt`

### Store Block

Access HCP Terraform variable sets:

```hcl
store "varset" "aws_credentials" {
  id       = "varset-ABC123"
  source   = "tfc-cloud-shared"
  category = "terraform"
}
```

### Deployment Block

Define deployment instances (minimum 1, maximum 20 per Stack):

```hcl
deployment "production" {
  inputs = {
    aws_region     = "us-west-1"
    instance_count = 3
    role_arn       = local.role_arn
    identity_token = identity_token.aws.jwt
  }
}

deployment "development" {
  inputs = {
    aws_region     = "us-east-1"
    instance_count = 1
    identity_token = identity_token.aws.jwt
  }
}
```

To destroy a deployment: set `destroy = true`, upload, approve destroy run, then remove the block.

### Linked Stacks

Publish outputs from one Stack and consume in another:

```hcl
# Network Stack
publish_output "vpc_id_network" {
  type  = string
  value = deployment.network.vpc_id
}

# Application Stack
upstream_input "network_stack" {
  type   = "stack"
  source = "app.terraform.io/my-org/my-project/networking-stack"
}

deployment "app" {
  inputs = {
    vpc_id = upstream_input.network_stack.vpc_id_network
  }
}
```

## CLI Commands

```bash
# Initialize and validate
terraform stacks init              # download providers, modules, generate lock file
terraform stacks validate          # check syntax without uploading
terraform stacks fmt               # format stack files

# Deploy (no plan/apply — upload triggers runs)
terraform stacks configuration upload

# Monitor
terraform stacks deployment-run list
terraform stacks deployment-group watch -deployment-group=...

# Approve
terraform stacks deployment-run approve-all-plans -deployment-run-id=...
terraform stacks deployment-run cancel -deployment-run-id=...
```

## Common Patterns

**Multi-Region**: Use `for_each` on providers and components to deploy across regions.

**Deferred Changes**: Stacks support deferred changes for dependencies where values are only known after apply (cluster endpoints, generated passwords).

## Best Practices

1. **Component granularity** — create components for logical infrastructure units that share a lifecycle
2. **Module compatibility** — modules cannot include provider blocks; test registry modules before use
3. **State isolation** — each deployment has its own isolated state
4. **Credentials** — use `ephemeral = true` for tokens; prefer workload identity (OIDC)
5. **Lock files** — always commit `.terraform.lock.hcl`
6. **Testing** — test in dev/staging deployments before production

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Circular dependencies | Refactor to break circular references or use intermediate components |
| Cannot destroy from UI | Set `destroy = true` in deployment block, upload, approve |
| Module compatibility | Test public registry modules before production; some have Stacks issues |
