---
name: carter-terraform
description: Write and review Terraform configurations following HashiCorp best practices
argument-hint: "[infrastructure component or Terraform config to review]"
---

<objective>
Write, review, and troubleshoot Terraform configurations following HashiCorp best practices and security standards.
</objective>

<guidelines>

## Terraform Best Practices

### Project Structure
```
infrastructure/
├── main.tf           # Primary resources
├── variables.tf      # Input variable declarations
├── outputs.tf        # Output declarations
├── versions.tf       # Required providers and Terraform version
├── terraform.tfvars  # Variable values (not committed for secrets)
├── locals.tf         # Local values and computed expressions
└── modules/
    └── <module>/
        ├── main.tf
        ├── variables.tf
        └── outputs.tf
```

### Naming Conventions
- Resources: `snake_case`, descriptive: `aws_instance.web_server` not `aws_instance.main`
- Variables: `snake_case`, include description and type
- Outputs: `snake_case`, include description
- Modules: `terraform-<provider>-<name>`

### State Management
- Always use remote state (S3 + DynamoDB, Terraform Cloud, etc.)
- Enable state locking
- Never commit `.tfstate` files
- Use workspaces or directory-based separation for environments

### Security
- Never hardcode secrets — use variables, Vault, or environment variables
- Use `sensitive = true` for secret variables and outputs
- Pin provider versions
- Enable encryption at rest and in transit for all storage resources
- Use IAM least-privilege policies
- Review `terraform plan` output carefully before `apply`

### Code Quality
- Run `terraform fmt` before committing
- Run `terraform validate` in CI
- Use `tflint` for additional linting
- Use `checkov` or `tfsec` for security scanning
- Keep modules small and focused (single responsibility)
- Use `count` and `for_each` appropriately (prefer `for_each` for named resources)

### Variables
- Always provide `description` and `type`
- Use `validation` blocks for input constraints
- Use `default` only when a sensible default exists
- Group related variables logically

</guidelines>

<review-checklist>

## Terraform Review Checklist

- [ ] Provider versions pinned in `versions.tf`
- [ ] Remote state configured with locking
- [ ] No hardcoded secrets or credentials
- [ ] All variables have description and type
- [ ] Resources have descriptive names
- [ ] Tags applied consistently (at minimum: Name, Environment, Owner)
- [ ] Security groups follow least-privilege
- [ ] Encryption enabled for storage and transit
- [ ] Outputs expose only necessary values
- [ ] `terraform fmt` passes
- [ ] `terraform validate` passes

</review-checklist>
