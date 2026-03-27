# Azure — CLI & VM Setup

Create an Azure VM for openhort. Azure's free tier includes a B1s
instance (1 vCPU, 1 GB RAM) for 12 months — enough for a
lightweight relay. For container-based deployments, see
[App Service Containers](containers.md).

## Create an Account

Sign up at [portal.azure.com](https://portal.azure.com). New
accounts get $200 credit for 30 days, plus 12 months of free-tier
services including a B1s Linux VM (750 hours/month).

!!! warning "Costs after trial"
    After 12 months the B1s VM is no longer free. Set up billing
    alerts in the Azure portal to avoid unexpected charges.

## Install the CLI

=== "macOS"

    ```bash
    brew install azure-cli
    ```

=== "Linux"

    ```bash
    curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
    ```

=== "pip"

    ```bash
    pip install azure-cli
    ```

## Authenticate

```bash
az login
```

This opens a browser for interactive login. After authenticating,
verify:

```bash
az account show --query '{name:name, id:id}' --output table
```

!!! tip "Multiple subscriptions"
    If you have more than one subscription, select the right one:

    ```bash
    az account list --output table
    az account set --subscription <subscription-id>
    ```

## Create a Resource Group

All Azure resources live in a resource group. Create one in the
region closest to you:

```bash
az group create \
  --name openhort-rg \
  --location westeurope
```

Common European regions: `westeurope` (Netherlands), `germanywestcentral`
(Frankfurt), `northeurope` (Ireland).

## Create the VM

```bash
az vm create \
  --resource-group openhort-rg \
  --name openhort-hub \
  --image Ubuntu2404 \
  --size Standard_B1s \
  --admin-username openhort \
  --generate-ssh-keys \
  --public-ip-sku Standard \
  --public-ip-address-allocation static
```

This creates the VM with:

- Ubuntu 24.04 LTS
- Static public IP (included with `Standard` SKU)
- SSH key from `~/.ssh/id_rsa.pub`
- Auto-created network security group

The output includes `publicIpAddress` — save it.

!!! info "Free-tier size"
    `Standard_B1s` is the free-tier eligible size (1 vCPU, 1 GB
    RAM). For heavier workloads, `Standard_B2s` (2 vCPU, 4 GB)
    costs ~$30/month.

## Open Firewall Ports

Azure's default NSG only allows SSH. Open HTTP and HTTPS:

```bash
az vm open-port \
  --resource-group openhort-rg \
  --name openhort-hub \
  --port 80 --priority 1010

az vm open-port \
  --resource-group openhort-rg \
  --name openhort-hub \
  --port 443 --priority 1020
```

Unlike Oracle, there's no secondary OS-level firewall to configure
on Azure Ubuntu images.

## SSH into the VM

```bash
ssh openhort@<public-ip>
```

## DNS Name

Azure gives you a free DNS label on the public IP:

```bash
az network public-ip update \
  --resource-group openhort-rg \
  --name openhort-hubPublicIP \
  --dns-name openhort-hub
```

Your VM is now reachable at
`openhort-hub.westeurope.cloudapp.azure.com` (region varies).

For a custom domain, add a CNAME or A record pointing to the
Azure DNS name or IP.

## Install Dependencies

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin nginx certbot python3-certbot-nginx

sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker
```

## TLS Certificate

With the DNS name:

```bash
sudo certbot --nginx -d openhort-hub.westeurope.cloudapp.azure.com
```

## Next Steps

- Deploy openhort on the VM directly, or
- Use [App Service Containers](containers.md) for a managed
  Docker deployment (no VM needed)
