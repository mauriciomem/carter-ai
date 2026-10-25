---
name: carter-packer
description: Build machine images with HashiCorp Packer following best practices. Covers HCL2 templates, provisioners, builders for AWS/Azure/Windows, and HCP Packer registry.
---

<objective>
Write, review, and troubleshoot Packer templates for building machine images following HashiCorp best practices.
</objective>

<routing>

## Specialized References

This file covers core Packer conventions. For specialized topics, use `read_file` to load the appropriate reference from the **same directory** as this SKILL.md before proceeding.

| File | Load when the request involves |
|------|-------------------------------|
| `aws.md` | AMIs, amazon-ebs builder, source_ami_filter, multi-region AMI copy, EC2 instances, AWS authentication |
| `azure.md` | Azure managed images, azure-arm builder, Azure Compute Gallery, service principals, Azure authentication |
| `windows.md` | Windows images, WinRM communicator, PowerShell provisioners, Windows Updates, Chocolatey, IIS |
| `hcp.md` | HCP Packer registry, hcp_packer_registry block, bucket_name, build metadata, image lifecycle, Terraform data source |

**How to load:** derive the directory path from this SKILL.md's location and read the sibling file. For example, if this file is at `~/.config/opencode/skills/carter-packer/SKILL.md`, read `~/.config/opencode/skills/carter-packer/aws.md`.

If the request does not match any specialized topic, use the core guidelines below without loading additional files.

</routing>

<guidelines>

## Template Structure

Every Packer template uses HCL2 with this structure:

```hcl
# packer block — required plugins and version constraints
packer {
  required_plugins {
    amazon = {
      source  = "github.com/hashicorp/amazon"
      version = "~> 1.8"
    }
  }
}

# variables — inputs with type and description
variable "region" {
  type        = string
  description = "Cloud region for the build"
  default     = "us-west-2"
}

# locals — computed values
locals {
  timestamp = regex_replace(timestamp(), "[- TZ:]", "")
}

# source — builder configuration (where and how to build)
source "amazon-ebs" "base" {
  region        = var.region
  instance_type = "t3.micro"
  ssh_username  = "ubuntu"
  ami_name      = "my-app-${local.timestamp}"

  source_ami_filter {
    filters = {
      name                = "ubuntu/images/*ubuntu-jammy-22.04-amd64-server-*"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    most_recent = true
    owners      = ["099720109477"]
  }
}

# build — what to do with the source (provisioning, post-processing)
build {
  sources = ["source.amazon-ebs.base"]

  provisioner "shell" {
    inline = [
      "sudo apt-get update",
      "sudo apt-get upgrade -y",
    ]
  }
}
```

## File Organization

| File | Purpose |
|------|---------|
| `main.pkr.hcl` | Source and build blocks |
| `variables.pkr.hcl` | Variable declarations |
| `*.auto.pkrvars.hcl` | Variable values (auto-loaded) |
| `scripts/` | Provisioning scripts (shell, PowerShell) |

Use `.pkr.hcl` extension for templates and `.pkrvars.hcl` for variable files.

## Variables

Every variable must include `type` and `description`:

```hcl
variable "instance_type" {
  type        = string
  description = "Instance size for the build VM"
  default     = "t3.micro"
}

variable "api_key" {
  type        = string
  description = "API key for artifact upload"
  sensitive   = true
}
```

- Use `default` only when a sensible default exists
- Use `sensitive = true` for secrets
- Never hardcode credentials in templates

## Locals

Use locals for computed values and timestamps:

```hcl
locals {
  timestamp  = regex_replace(timestamp(), "[- TZ:]", "")
  image_name = "${var.app_name}-${local.timestamp}"
}
```

Always include a timestamp in image names to ensure uniqueness.

## Provisioners

### Shell (Linux)

```hcl
provisioner "shell" {
  inline = [
    "sudo apt-get update",
    "sudo apt-get install -y nginx",
  ]
}

provisioner "shell" {
  script = "scripts/setup.sh"
}

provisioner "shell" {
  scripts = [
    "scripts/install-deps.sh",
    "scripts/configure-app.sh",
  ]
}
```

### File

```hcl
provisioner "file" {
  source      = "configs/app.conf"
  destination = "/tmp/app.conf"
}

provisioner "shell" {
  inline = ["sudo mv /tmp/app.conf /etc/app/app.conf"]
}
```

File provisioner uploads to user home or `/tmp`. Move to final destination with a shell provisioner.

### Execution Order

Provisioners run **top to bottom** within a build block. Order matters — install dependencies before configuring applications.

## Build Commands

```bash
packer init .          # download plugins
packer fmt .           # format templates
packer validate .      # check syntax
packer build .         # build image
packer build -var "region=us-east-1" .  # with variable override
```

## Plugin Management

Pin plugin versions explicitly:

```hcl
packer {
  required_plugins {
    amazon = {
      source  = "github.com/hashicorp/amazon"
      version = "~> 1.8"
    }
  }
}
```

Run `packer init .` after adding or updating plugins. Use `packer init -upgrade .` to update within version constraints.

## Best Practices

1. **Unique image names** — always include a timestamp or build number
2. **Pin plugin versions** — use `~>` for minor version flexibility
3. **Validate before build** — run `packer validate` in CI before building
4. **Use variables** — never hardcode regions, instance types, or credentials
5. **Script files** — extract complex provisioning into separate scripts under `scripts/`
6. **Cleanup** — remove temp files, package caches, and logs before image finalization
7. **Tags/labels** — apply consistent metadata (Name, BuildDate, ManagedBy)

## Version Control

**Never commit:** `*.pkrvars.hcl` with secrets, `.packer.d/`

**Always commit:** all `.pkr.hcl` files, `scripts/`, plugin lock files

</guidelines>
