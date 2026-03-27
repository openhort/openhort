# Oracle Cloud — Account Setup

Create an Oracle Cloud account and understand the free tier.

## Create an Account

1. Go to [cloud.oracle.com](https://cloud.oracle.com) and click
   **Sign Up**
2. Enter your email, name, and country
3. Verify your email
4. Provide a credit card for identity verification

!!! info "Credit card"
    Oracle requires a card to verify your identity but does **not**
    charge it for free-tier resources. You will not be billed
    unless you manually upgrade to a paid account.

## Free Tier Overview

As of early 2026, the Always Free tier includes:

| Resource | Allowance |
|----------|-----------|
| **ARM Compute** | Up to 4 VMs (Ampere A1), 24 GB RAM, 4 OCPUs total |
| **Block Storage** | 200 GB |
| **Networking** | Reserved public IPs, 10 TB/month outbound |
| **Database** | 2 Autonomous Databases (20 GB each) |
| **Object Storage** | 20 GB |

Unlike AWS and Azure 12-month trials, Oracle's Always Free
resources **do not expire**. However, Oracle reserves the right to
reclaim idle free-tier instances.

!!! warning "Costs outside the free tier"
    Resources beyond the free-tier limits (e.g. a larger VM shape,
    extra block volumes, or a paid database) will incur charges.
    Always check the shape and resource type before provisioning.

## Choose a Region

You pick a **home region** during signup. This is where your
free-tier resources live and **cannot be changed** without creating
a new tenancy.

Pick the region closest to you or your users. Common choices:

| Location | Region |
|----------|--------|
| Frankfurt | `eu-frankfurt-1` |
| Amsterdam | `eu-amsterdam-1` |
| London | `uk-london-1` |
| US East | `us-ashburn-1` |
| US West | `us-phoenix-1` |

!!! tip "Free tier capacity"
    Popular regions sometimes run out of free ARM capacity. If VM
    creation fails with "Out of host capacity" later, you'll need
    to retry periodically — the region choice itself is permanent.

## Navigate the Console

After signup, the Oracle Cloud Console is at
[cloud.oracle.com](https://cloud.oracle.com). Key locations:

| Page | URL | What's there |
|------|-----|-------------|
| My Profile | [identity/domains/my-profile](https://cloud.oracle.com/identity/domains/my-profile) | User OCID, API keys |
| Tenancy | [tenancy](https://cloud.oracle.com/tenancy) | Tenancy OCID, home region |
| Tokens & Keys | [my-profile/auth-tokens](https://cloud.oracle.com/identity/domains/my-profile/auth-tokens) | API keys, auth tokens |
| Compute | [compute/instances](https://cloud.oracle.com/compute/instances) | VM instances |
| Networking | [networking/vcns](https://cloud.oracle.com/networking/vcns) | VCNs, subnets, security lists |

!!! info "OCIDs"
    Oracle identifies every resource with an **OCID** (Oracle Cloud
    Identifier) — a long string like `ocid1.user.oc1..aaaa…`. You'll
    need your User OCID and Tenancy OCID in the next step.

## Next Steps

Account ready — proceed to [CLI Setup](cli.md) to install and
authenticate the Oracle Cloud CLI.
