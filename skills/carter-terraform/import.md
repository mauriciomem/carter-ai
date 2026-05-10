# Terraform Import & Search

Discover existing cloud resources using Terraform Search queries and import them into Terraform management. Covers bulk import workflows, query syntax, generated config cleanup, and manual import blocks.

## Decision Tree

1. **Identify target resource type** (e.g., aws_s3_bucket, aws_instance)
2. **Check Terraform version**: `terraform version`
3. **Choose workflow**:
   - **Terraform >= 1.14 + provider supports list resources**: Use Terraform Search workflow
   - **Otherwise**: Use manual import blocks

## Check Provider Support First

Before starting, verify the target resource type is supported for list queries:

```bash
terraform providers schema -json | jq '.provider_schemas | to_entries | map({key: (.key | split("/")[-1]), value: (.value.list_resource_schemas // {} | keys)})'
```

## Prerequisites

Ensure you have a configuration with the required provider:

```hcl
# terraform.tf
terraform {
  required_version = ">= 1.14"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
```

Run `terraform init` to download the provider, then proceed with queries.

## Query File Structure

Query files use `.tfquery.hcl` extension and support `provider`, `list`, `variable`, and `locals` blocks:

```hcl
# discovery.tfquery.hcl
provider "aws" {
  region = "us-west-2"
}

list "aws_instance" "all" {
  provider = aws
}
```

## List Block Syntax

```hcl
list "<list_type>" "<symbolic_name>" {
  provider = <provider_reference>  # Required

  # Optional: provider-specific filter configuration
  config {
    filter {
      name   = "<filter_name>"
      values = ["<value1>", "<value2>"]
    }
  }

  # Optional: limit results
  limit = 100
}
```

## Query Examples

### Basic Discovery

```hcl
list "aws_instance" "all" {
  provider = aws
}
```

### Filtered Discovery

```hcl
# By tag
list "aws_instance" "production" {
  provider = aws

  config {
    filter {
      name   = "tag:Environment"
      values = ["production"]
    }
  }
}

# By instance type
list "aws_instance" "large" {
  provider = aws

  config {
    filter {
      name   = "instance-type"
      values = ["t3.large", "t3.xlarge"]
    }
  }
}
```

### Multi-Region Discovery

```hcl
locals {
  regions = ["us-west-2", "us-east-1", "eu-west-1"]
}

list "aws_instance" "all_regions" {
  for_each = toset(local.regions)
  provider = aws

  config {
    region = each.value
  }
}
```

### Parameterized Queries

```hcl
variable "target_environment" {
  type    = string
  default = "staging"
}

list "aws_instance" "by_env" {
  provider = aws

  config {
    filter {
      name   = "tag:Environment"
      values = [var.target_environment]
    }
  }
}
```

## Running Queries

```bash
terraform query                                    # discover resources
terraform query -generate-config-out=imported.tf   # generate config
terraform query -var='target_environment=production' # with variables
```

## Post-Generation Cleanup

Generated configuration includes all attributes. Clean up by:

1. Remove computed/read-only attributes (`arn`, `id`, etc.)
2. Replace hardcoded values with variables
3. Add proper resource naming
4. Organize into appropriate files

```hcl
# Before: generated
resource "aws_instance" "all_0" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t2.micro"
  arn           = "arn:aws:ec2:..."  # Remove — computed
  id            = "i-0abc123"        # Remove — computed
}

# After: cleaned
resource "aws_instance" "web_server" {
  ami           = var.ami_id
  instance_type = var.instance_type
  subnet_id     = var.subnet_id

  tags = {
    Name        = "web-server"
    Environment = var.environment
  }
}
```

## Identity-Based Import (Terraform 1.12+)

Generated imports use identity-based import:

```hcl
import {
  to       = aws_instance.web
  provider = aws
  identity = {
    account_id = "123456789012"
    id         = "i-0abc123"
    region     = "us-west-2"
  }
}
```

## Import Blocks (Pre-1.14 or Manual)

```hcl
import {
  to = aws_instance.web
  id = "i-0abc123"
}
```

## Complete Workflow Example

```hcl
# discovery.tfquery.hcl
provider "aws" {
  region = "us-west-2"
}

list "aws_instance" "team_instances" {
  provider = aws

  config {
    filter {
      name   = "tag:Owner"
      values = ["platform"]
    }
    filter {
      name   = "instance-state-name"
      values = ["running"]
    }
  }

  limit = 50
}
```

```bash
terraform init
terraform query
terraform query -generate-config-out=generated.tf
# Review and clean generated.tf
terraform plan
terraform apply
```

## Best Practices

- Start broad, then add filters to narrow results
- Use `limit` to prevent overwhelming output
- Test queries before generating configuration
- Review all generated code before applying
- Remove unnecessary default values
- Use consistent naming conventions

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "No list resources found" | Check provider version supports list resources |
| Query returns empty | Verify region and filter values |
| Generated config has errors | Remove computed attributes, fix deprecated arguments |
| Import fails | Ensure resource not already in state |
