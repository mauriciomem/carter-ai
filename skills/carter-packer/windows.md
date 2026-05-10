# Windows Image Builder

Platform-agnostic patterns for building Windows images with Packer using WinRM communicator and PowerShell provisioners.

> Windows builds take 45-120 minutes due to Windows Updates. Failed builds may leave resources running — always verify cleanup.

## WinRM Communicator Setup

Windows requires WinRM instead of SSH for Packer communication.

### AWS Example

```hcl
source "amazon-ebs" "windows" {
  region        = "us-west-2"
  instance_type = "t3.medium"

  source_ami_filter {
    filters = {
      name = "Windows_Server-2022-English-Full-Base-*"
    }
    most_recent = true
    owners      = ["amazon"]
  }

  ami_name = "windows-server-2022-${local.timestamp}"

  communicator   = "winrm"
  winrm_username = "Administrator"
  winrm_use_ssl  = true
  winrm_insecure = true
  winrm_timeout  = "15m"

  user_data_file = "scripts/setup-winrm.ps1"
}
```

### Azure Example

```hcl
source "azure-arm" "windows" {
  subscription_id = var.subscription_id
  use_azure_cli_auth = true

  managed_image_resource_group_name = "images-rg"
  managed_image_name                = "windows-${local.timestamp}"

  os_type         = "Windows"
  image_publisher = "MicrosoftWindowsServer"
  image_offer     = "WindowsServer"
  image_sku       = "2022-datacenter-g2"

  location = "East US"
  vm_size  = "Standard_D2s_v3"

  # Azure auto-configures WinRM
  communicator   = "winrm"
  winrm_use_ssl  = true
  winrm_insecure = true
  winrm_timeout  = "15m"
  winrm_username = "packer"
}
```

### WinRM Setup Script (scripts/setup-winrm.ps1)

Required for AWS; Azure configures WinRM automatically.

```powershell
<powershell>
winrm quickconfig -q
winrm set winrm/config '@{MaxTimeoutms="1800000"}'
winrm set winrm/config/service '@{AllowUnencrypted="true"}'
winrm set winrm/config/service/auth '@{Basic="true"}'

netsh advfirewall firewall add rule name="WinRM 5985" protocol=TCP dir=in localport=5985 action=allow
netsh advfirewall firewall add rule name="WinRM 5986" protocol=TCP dir=in localport=5986 action=allow

net stop winrm
net start winrm
</powershell>
```

## PowerShell Provisioners

### Install Software

```hcl
build {
  sources = ["source.amazon-ebs.windows"]

  provisioner "powershell" {
    inline = [
      "Set-ExecutionPolicy Bypass -Scope Process -Force",
      "iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))"
    ]
  }

  provisioner "powershell" {
    inline = [
      "choco install -y googlechrome",
      "choco install -y 7zip",
    ]
  }

  provisioner "powershell" {
    inline = [
      "Install-WindowsFeature -Name Web-Server -IncludeManagementTools"
    ]
  }
}
```

### Windows Updates

```hcl
provisioner "powershell" {
  inline = [
    "Install-PackageProvider -Name NuGet -Force",
    "Install-Module -Name PSWindowsUpdate -Force",
    "Import-Module PSWindowsUpdate",
    "Get-WindowsUpdate -Install -AcceptAll -AutoReboot",
  ]
  timeout = "2h"
}

provisioner "windows-restart" {
  restart_timeout = "30m"
}
```

### Cleanup

```hcl
provisioner "powershell" {
  inline = [
    "Remove-Item -Path 'C:\\Windows\\Temp\\*' -Recurse -Force -ErrorAction SilentlyContinue",
    "Stop-Service -Name wuauserv -Force",
    "Remove-Item -Path 'C:\\Windows\\SoftwareDistribution\\*' -Recurse -Force -ErrorAction SilentlyContinue",
    "Start-Service -Name wuauserv",
  ]
}
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| WinRM timeout | Increase `winrm_timeout` to 15m+; verify security group allows ports 5985/5986; check user data script completed |
| Execution policy error | Prefix commands with `Set-ExecutionPolicy Bypass -Scope Process -Force` |
| Long build times | Windows Updates can take 1-2h; use pre-patched base images; set provisioner `timeout = "2h"` |
