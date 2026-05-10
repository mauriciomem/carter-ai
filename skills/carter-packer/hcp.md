# HCP Packer Registry

Push Packer build metadata to HCP Packer for image lifecycle management, versioning, and governance.

## Basic Registry Configuration

Add `hcp_packer_registry` inside the `build` block:

```hcl
build {
  sources = ["source.amazon-ebs.ubuntu"]

  hcp_packer_registry {
    bucket_name = "web-server"
    description = "Ubuntu 22.04 base image for web servers"

    bucket_labels = {
      "os"   = "ubuntu"
      "team" = "platform"
    }

    build_labels = {
      "build-time" = local.timestamp
      "git-commit" = var.git_commit
    }
  }

  provisioner "shell" {
    inline = [
      "sudo apt-get update",
      "sudo apt-get upgrade -y",
    ]
  }
}
```

## Authentication

```bash
export HCP_CLIENT_ID="your-service-principal-client-id"
export HCP_CLIENT_SECRET="your-service-principal-secret"
export HCP_ORGANIZATION_ID="your-org-id"
export HCP_PROJECT_ID="your-project-id"

packer build .
```

Create an HCP service principal with Contributor role on the project via HCP Portal > Access Control (IAM).

## Configuration Options

### bucket_name (required)

The image identifier in the registry. Must stay **consistent** across builds — never include timestamps.

```hcl
bucket_name = "web-server"  # Constant across builds
```

### bucket_labels (optional)

Metadata at the bucket level. Updated with each build.

```hcl
bucket_labels = {
  "os"        = "ubuntu"
  "team"      = "platform"
  "component" = "web"
}
```

### build_labels (optional)

Per-iteration metadata. Immutable after build completes. Use for changing data like git SHAs and dates.

```hcl
build_labels = {
  "build-time" = local.timestamp
  "git-commit" = var.git_commit
}
```

## Consuming in Terraform

Use the `hcp_packer_artifact` data source to reference registry images:

```hcl
data "hcp_packer_artifact" "ubuntu" {
  bucket_name  = "web-server"
  channel_name = "production"
  platform     = "aws"
  region       = "us-west-2"
}

resource "aws_instance" "web" {
  ami           = data.hcp_packer_artifact.ubuntu.external_identifier
  instance_type = "t3.micro"
}
```

## CI/CD Integration (GitHub Actions)

```yaml
name: Build and Push to HCP Packer

on:
  push:
    branches: [main]

env:
  HCP_CLIENT_ID: ${{ secrets.HCP_CLIENT_ID }}
  HCP_CLIENT_SECRET: ${{ secrets.HCP_CLIENT_SECRET }}
  HCP_ORGANIZATION_ID: ${{ secrets.HCP_ORGANIZATION_ID }}
  HCP_PROJECT_ID: ${{ secrets.HCP_PROJECT_ID }}

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-packer@main
      - run: |
          packer init .
          packer build -var "git_commit=${{ github.sha }}" .
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Authentication failed | Verify HCP_CLIENT_ID/SECRET; ensure Contributor role; check org/project IDs |
| Bucket name mismatch | Keep `bucket_name` constant for the same image type — changing it creates a new bucket |
| Build fails immediately | Packer aborts if it can't reach HCP API — check network connectivity |
