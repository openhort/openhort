# Oracle Cloud — VM & Networking

Create a free-tier ARM instance, assign a static IP, and open
firewall ports for openhort.

!!! info "Prerequisites"
    Complete [Account Setup](account.md) and [CLI Setup](cli.md)
    first. All commands below assume a working `oci` CLI.

## Understand the Network Topology

Oracle Cloud VMs live inside a **VCN** (Virtual Cloud Network).
Free-tier accounts get a default VCN with a public subnet.

```mermaid
flowchart LR
    Internet -->|"ports 80, 443"| SL[Security List]
    SL --> Subnet
    Subnet --> VM[openhort VM]
    VM -->|iptables| App[openhort :8940]
```

Traffic passes through **two** firewalls: the cloud security list
and the OS-level iptables. Both must allow the port.

## Find Your Compartment and Network

```bash
# Your tenancy OCID is also your root compartment
COMPARTMENT=$(grep tenancy ~/.oci/config | cut -d= -f2)

# List VCNs
oci network vcn list \
  --compartment-id $COMPARTMENT \
  --query 'data[].{name:"display-name", id:id}' \
  --output table

# List subnets (use the VCN ID from above)
oci network subnet list \
  --compartment-id $COMPARTMENT \
  --vcn-id <vcn-ocid> \
  --query 'data[].{name:"display-name", id:id, public:"prohibit-public-ip-on-vnic"}' \
  --output table
```

Use the **public** subnet (where `prohibit-public-ip-on-vnic` is
`false`).

## Find the Availability Domain

```bash
oci iam availability-domain list \
  --compartment-id $COMPARTMENT \
  --query 'data[].name' --raw-output
```

Free-tier ARM instances are usually in `AD-1` or `AD-2` depending
on the region.

## Find the Ubuntu Image

```bash
oci compute image list \
  --compartment-id $COMPARTMENT \
  --operating-system "Canonical Ubuntu" \
  --shape "VM.Standard.A1.Flex" \
  --sort-by TIMECREATED --sort-order DESC \
  --query 'data[0].{name:"display-name", id:id}' \
  --output table
```

Pick the latest **Ubuntu 24.04** (Noble) image.

## Create the VM

```bash
oci compute instance launch \
  --compartment-id $COMPARTMENT \
  --availability-domain <ad-name> \
  --shape VM.Standard.A1.Flex \
  --shape-config '{"ocpus": 1, "memoryInGBs": 6}' \
  --image-id <ubuntu-image-id> \
  --subnet-id <public-subnet-ocid> \
  --assign-public-ip true \
  --ssh-authorized-keys-file ~/.ssh/id_rsa.pub \
  --display-name openhort-hub
```

!!! tip "Free-tier shape limits"
    The Always Free ARM allocation is **4 OCPUs / 24 GB RAM total**
    across all A1 instances. A single VM with 1 OCPU / 6 GB is a
    good starting point — you can resize later.

    If you get **"Out of host capacity"**, the region is
    temporarily full. Wait a few hours and retry, or try a
    different availability domain.

??? example "Shape config options"

    | Config | Description |
    |--------|-------------|
    | `{"ocpus": 1, "memoryInGBs": 6}` | Lightweight hub |
    | `{"ocpus": 2, "memoryInGBs": 12}` | Hub + Docker workloads |
    | `{"ocpus": 4, "memoryInGBs": 24}` | Full free-tier allocation |

## SSH into the VM

Once the instance reaches `RUNNING` state:

```bash
# Get the public IP
oci compute instance list-vnics \
  --instance-id <instance-ocid> \
  --query 'data[0]."public-ip"' --raw-output

# Connect (default user is 'ubuntu' for Ubuntu images)
ssh ubuntu@<public-ip>
```

## Reserve a Static IP

By default the VM gets an **ephemeral** IP that changes on reboot.
Convert it to a **reserved** (static) IP — free on Oracle Cloud.

```bash
# Create a reserved public IP
oci network public-ip create \
  --compartment-id $COMPARTMENT \
  --lifetime RESERVED \
  --display-name openhort-ip
```

Then assign it to your VM's VNIC:

```bash
# Get the VM's private IP OCID
PRIVATE_IP=$(oci compute instance list-vnics \
  --instance-id <instance-ocid> \
  --query 'data[0]."private-ip-id"' --raw-output)

# Assign the reserved IP
oci network public-ip update \
  --public-ip-id <reserved-ip-ocid> \
  --private-ip-id $PRIVATE_IP
```

!!! tip "Console alternative"
    **Networking → IP Management → Reserved Public IPs** in the
    web console is often easier for a one-time setup.

## Open Firewall Ports

### Cloud Security List

Oracle's default security list blocks all inbound TCP except SSH (22).
Add rules for HTTP and HTTPS:

```bash
# Get the security list ID
SL_ID=$(oci network security-list list \
  --compartment-id $COMPARTMENT \
  --vcn-id <vcn-ocid> \
  --query 'data[0].id' --raw-output)

# Get current rules (save them — you need to include existing rules)
oci network security-list get \
  --security-list-id $SL_ID \
  --query 'data."ingress-security-rules"' > /tmp/rules.json
```

Edit `/tmp/rules.json` to add the new rules, then update:

```bash
oci network security-list update \
  --security-list-id $SL_ID \
  --ingress-security-rules file:///tmp/rules.json \
  --force
```

??? example "Ingress rules to add"

    Append these objects to the existing rules array:

    ```json
    {
      "source": "0.0.0.0/0",
      "protocol": "6",
      "tcpOptions": {
        "destinationPortRange": {"min": 80, "max": 80}
      },
      "isStateless": false
    },
    {
      "source": "0.0.0.0/0",
      "protocol": "6",
      "tcpOptions": {
        "destinationPortRange": {"min": 443, "max": 443}
      },
      "isStateless": false
    }
    ```

### OS-Level iptables

Oracle's Ubuntu images ship with restrictive iptables rules on top
of the cloud firewall. SSH into the VM and open the ports there too:

```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

!!! danger "Both layers required"
    If you only update the security list but not iptables (or vice
    versa), traffic will still be blocked. You must open ports in
    **both** the cloud security list and OS iptables.

## Install openhort Dependencies

Once SSH'd in:

```bash
# System packages
sudo apt update
sudo apt install -y docker.io docker-compose-plugin nginx certbot python3-certbot-nginx

# Enable Docker
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker
```

## DNS

Oracle doesn't provide a free hostname. Options:

| Method | Cost | Example |
|--------|------|---------|
| Own domain | ~$10/year | `hub.yourdomain.com` → A record to reserved IP |
| [DuckDNS](https://www.duckdns.org) | Free | `openhort.duckdns.org` |
| [No-IP](https://www.noip.com) | Free (with renewal) | `openhort.ddns.net` |

With a domain pointed at your IP, get a TLS certificate:

```bash
sudo certbot --nginx -d hub.yourdomain.com
```

## Next Steps

Your Oracle Cloud VM is running with a static IP and open ports.
From here:

- Deploy openhort as a hub/relay
- Set up the [access server tunnel](../../../develop/sandbox-sessions.md)
- Or use it as a [multi-node worker](../../multi-node.md)
