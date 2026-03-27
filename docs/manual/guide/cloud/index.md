# Cloud Providers

Run an openhort hub on a cloud VM — a persistent relay so you can
reach your machines from anywhere.

!!! warning "Verify before you provision"
    Cloud providers change interfaces, pricing, and free-tier terms
    without notice. These guides were written in early 2026 — always
    verify current pricing on your provider's website before
    creating resources.

## Which Provider?

| Provider | Free Tier VM | Static IP | Best for |
|----------|-------------|-----------|----------|
| **Oracle Cloud** | 1–4 ARM VMs, 24 GB RAM total | Reserved IP (free) | Long-term free hub |
| **Azure** | B1s (1 vCPU, 1 GB) for 12 months | DNS name included | Container deployments |

Oracle's free tier is the most generous — enough to run openhort,
nginx, Docker, and more without ever paying. Azure is better if you
need managed containers (App Service) or already have an Azure
subscription.

## Recommended OS

Use **Ubuntu Server 24.04 LTS** on both providers:

- Smallest footprint for a proxy/hub
- No license cost (unlike RHEL or Windows)
- Docker installs cleanly via `apt`
- First-class cloud integration and kernel tuning

## Guides

**Oracle Cloud:**

- [Account Setup](oracle/account.md) — sign up, region selection, free-tier overview
- [CLI Setup](oracle/cli.md) — install OCI CLI, API keys, authentication
- [VM & Networking](oracle/vm.md) — create instance, static IP, firewall, DNS

**Azure:**

- [Account & CLI Setup](azure/setup.md) — sign up, install CLI, create a VM
- [App Service Containers](azure/containers.md) — managed Docker deployment
