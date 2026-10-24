# Azure Image Builder

Build Azure managed images and Azure Compute Gallery images using Packer's `azure-arm` builder.

## Basic Managed Image

```hcl
packer {
  required_plugins {
    azure = {
      source  = "github.com/hashicorp/azure"
      version = "~> 2.6"
    }
  }
}

variable "subscription_id" {
  type = string
}

variable "resource_group" {
  type    = string
  default = "packer-images-rg"
}

locals {
  timestamp = regex_replace(timestamp(), "[- TZ:]", "")
}

source "azure-arm" "ubuntu" {
  subscription_id                   = var.subscription_id
  use_azure_cli_auth                = true
  managed_image_resource_group_name = var.resource_group
  managed_image_name                = "my-app-${local.timestamp}"

  os_type         = "Linux"
  image_publisher = "Canonical"
  image_offer     = "0001-com-ubuntu-server-jammy"
  image_sku       = "22_04-lts-gen2"

  location = "East US"
  vm_size  = "Standard_B2s"

  azure_tags = {
    Name      = "my-app"
    BuildDate = local.timestamp
  }
}

build {
  sources = ["source.azure-arm.ubuntu"]

  provisioner "shell" {
    inline = [
      "sudo apt-get update",
      "sudo apt-get upgrade -y",
    ]
  }
}
```

## Azure Compute Gallery

```hcl
source "azure-arm" "ubuntu" {
  subscription_id = var.subscription_id
  use_azure_cli_auth = true

  os_type         = "Linux"
  image_publisher = "Canonical"
  image_offer     = "0001-com-ubuntu-server-jammy"
  image_sku       = "22_04-lts-gen2"

  location = "East US"
  vm_size  = "Standard_B2s"

  shared_image_gallery_destination {
    resource_group       = "gallery-rg"
    gallery_name         = "myImageGallery"
    image_name           = "ubuntu-webapp"
    image_version        = "1.0.${formatdate("YYYYMMDD", timestamp())}"
    replication_regions  = ["East US", "West US 2"]
    storage_account_type = "Standard_LRS"
  }
}
```

## Authentication

### Azure CLI (preferred for local development)

```hcl
source "azure-arm" "ubuntu" {
  use_azure_cli_auth = true
  subscription_id    = var.subscription_id
  # ...
}
```

### Service Principal (for CI/CD)

```bash
az ad sp create-for-rbac \
  --name "packer-sp" \
  --role Contributor \
  --scopes /subscriptions/<subscription-id>

export ARM_CLIENT_ID="<client-id>"
export ARM_CLIENT_SECRET="<client-secret>"
export ARM_SUBSCRIPTION_ID="<subscription-id>"
export ARM_TENANT_ID="<tenant-id>"
```

```hcl
source "azure-arm" "ubuntu" {
  client_id       = var.client_id
  client_secret   = var.client_secret
  subscription_id = var.subscription_id
  tenant_id       = var.tenant_id
  # ...
}
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Authentication failed | Verify service principal credentials; ensure Contributor role on resource group |
| Gallery version exists | Image versions are immutable — use unique version numbers with date/build number |
| Timeout during provisioning | Check network connectivity from build VM; verify NSG rules; increase timeout |
