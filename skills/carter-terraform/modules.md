# Terraform Module Refactoring

Transform monolithic Terraform configurations into reusable, maintainable modules following HashiCorp's module design principles. Covers interface design, encapsulation, composition, state migration, and common pitfalls.

## When to Refactor

- Repeated resource patterns across configurations
- Groups of tightly coupled resources (VPC + subnets)
- Resources with shared lifecycle
- Configuration exceeding ~200 lines

## Module Structure

```
modules/<module>/
├── main.tf           # Resources
├── variables.tf      # Input contract
├── outputs.tf        # Output contract
├── README.md         # Usage documentation
└── tests/
    ├── defaults_unit_test.tftest.hcl
    └── integration_test.tftest.hcl
```

Module naming: `terraform-<provider>-<name>`

## Interface Design

```hcl
# Define clear input contract with validation
variable "network_config" {
  description = "Network configuration parameters"
  type = object({
    cidr_block         = string
    availability_zones = list(string)
    enable_nat         = bool
  })

  validation {
    condition     = can(cidrhost(var.network_config.cidr_block, 0))
    error_message = "CIDR block must be valid IPv4 CIDR."
  }
}

# Define output contract
output "vpc_id" {
  description = "ID of the created VPC"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "Map of private subnet IDs"
  value       = { for k, v in aws_subnet.private : k => v.id }
}
```

## Encapsulation

**Include in module:** tightly coupled resources, shared lifecycle, clear boundaries.

**Keep separate:** cross-cutting concerns (monitoring, tagging), different lifecycles, provider-specific configurations.

## Refactoring Example

### Before: Monolithic

```hcl
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  tags = { Name = "production-vpc" }
}

resource "aws_subnet" "public_1" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "us-east-1a"
  tags = { Name = "public-subnet-1" }
}

resource "aws_subnet" "public_2" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.2.0/24"
  availability_zone = "us-east-1b"
  tags = { Name = "public-subnet-2" }
}
```

### After: Modular

```hcl
# modules/vpc/main.tf
resource "aws_vpc" "main" {
  cidr_block           = var.cidr_block
  enable_dns_hostnames = var.enable_dns_hostnames

  tags = merge(var.tags, { Name = var.name })
}

resource "aws_subnet" "public" {
  for_each = var.create_public_subnets ? toset(var.availability_zones) : []

  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.cidr_block, 8, index(var.availability_zones, each.value))
  availability_zone       = each.value
  map_public_ip_on_launch = true

  tags = merge(var.tags, {
    Name = "${var.name}-public-${each.value}"
    Type = "public"
  })
}

# Root configuration
module "vpc" {
  source = "./modules/vpc"

  name               = "production"
  cidr_block         = "10.0.0.0/16"
  availability_zones = ["us-east-1a", "us-east-1b", "us-east-1c"]

  tags = {
    Environment = "production"
    ManagedBy   = "Terraform"
  }
}
```

## Refactoring Patterns

### Pattern 1: Resource Grouping

Extract related resources into cohesive modules:
- Networking (VPC, Subnets, Route Tables)
- Compute (ASG, Launch Templates, Load Balancers)
- Data (RDS, ElastiCache, S3)

### Pattern 2: Composition

```hcl
# Small, focused modules composed together
module "vpc" {
  source = "./modules/vpc"
}

module "security_groups" {
  source = "./modules/security-groups"
  vpc_id = module.vpc.vpc_id
}

module "application" {
  source     = "./modules/application"
  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnet_ids
  sg_ids     = module.security_groups.app_sg_ids
}
```

### Pattern 3: Configuration Layering

```hcl
# Base module with defaults
module "vpc_base" {
  source = "./modules/vpc-base"
}

# Environment-specific wrapper
module "vpc_prod" {
  source = "./modules/vpc-production"
  # Inherits from base, adds prod-specific config
}
```

## State Migration with Moved Blocks (Terraform 1.1+)

```hcl
# migration.tf
moved {
  from = aws_vpc.main
  to   = module.vpc.aws_vpc.main
}

moved {
  from = aws_subnet.public_1
  to   = module.vpc.aws_subnet.public["us-east-1a"]
}

moved {
  from = aws_subnet.public_2
  to   = module.vpc.aws_subnet.public["us-east-1b"]
}

moved {
  from = aws_internet_gateway.main
  to   = module.vpc.aws_internet_gateway.main[0]
}
```

### Manual State Migration (Pre-1.1)

```bash
terraform state mv aws_vpc.main module.vpc.aws_vpc.main
terraform state mv aws_subnet.public_1 'module.vpc.aws_subnet.public["us-east-1a"]'
```

Always run `terraform plan` after migration to verify no changes are planned.

## Common Pitfalls

### Over-Abstraction

```hcl
# Bad — too generic, hard to validate
variable "resources" {
  type = map(map(any))
}

# Good — specific, typed interfaces
variable "database_config" {
  type = object({
    engine         = string
    instance_class = string
  })
}
```

### Tight Coupling

```hcl
# Bad — modules referencing each other directly
# Good — pass dependencies through the root module
module "compute" {
  source = "./modules/compute"
}

resource "aws_eip" "app" {
  instance = module.compute.instance_id
}
```

### State Migration Errors

Always test migration in non-production first:

```bash
terraform plan -out=migration.tfplan
terraform show migration.tfplan
# Apply only if plan shows no changes
terraform apply migration.tfplan
```

## Version Control for Modules

```hcl
# Pin to specific versions in production
module "vpc" {
  source  = "git::https://github.com/org/terraform-modules.git//vpc?ref=v1.2.0"
}
```

## Success Criteria

- [ ] Module has single, well-defined responsibility
- [ ] All variables have descriptions, types, and validation where needed
- [ ] Outputs provide sufficient information for consumers
- [ ] Documentation includes usage examples
- [ ] Tests verify module behavior
- [ ] State migration completed without resource recreation
