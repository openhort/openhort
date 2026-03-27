# Oracle Cloud — CLI Setup

Install the OCI CLI and authenticate it with your Oracle Cloud
account.

!!! info "Prerequisites"
    You need an Oracle Cloud account with your User OCID and
    Tenancy OCID. See [Account Setup](account.md) if you haven't
    done this yet.

## Install the CLI

=== "macOS (Homebrew)"

    ```bash
    brew install oci-cli
    ```

=== "Linux / manual"

    ```bash
    bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"
    ```

=== "pip"

    ```bash
    pip install oci-cli
    ```

Verify the installation:

```bash
oci --version
```

## Gather Your OCIDs

You need two identifiers from the Oracle Cloud Console:

| Value | Where to find it | Format |
|-------|-----------------|--------|
| **User OCID** | [My Profile](https://cloud.oracle.com/identity/domains/my-profile) | `ocid1.user.oc1..aaaa…` |
| **Tenancy OCID** | [Tenancy](https://cloud.oracle.com/tenancy) | `ocid1.tenancy.oc1..aaaa…` |

Both are long strings — copy them exactly from the console.

## Configure the CLI

```bash
oci setup config
```

The interactive wizard asks:

| Prompt | What to enter |
|--------|--------------|
| Config location | Accept default (`~/.oci/config`) |
| User OCID | Paste from My Profile |
| Tenancy OCID | Paste from Tenancy page |
| Region | Number from the list (e.g. `35` for `eu-frankfurt-1`) |
| Generate new API key? | `Y` |
| Key directory | Accept default (`~/.oci`) |
| Key name | Any name (e.g. `oci_api_key`) |
| Passphrase | **Leave empty** — just press Enter |

!!! warning "Do not set a passphrase"
    A passphrase on the API key causes authentication errors:

    ```
    TypeError: Password was not given but private key is encrypted
    ```

    If you accidentally set one, regenerate without it:

    ```bash
    openssl genrsa -out ~/.oci/<key_name>.pem 2048
    openssl rsa -pubout -in ~/.oci/<key_name>.pem \
      -out ~/.oci/<key_name>_public.pem
    chmod 600 ~/.oci/<key_name>.pem
    ```

    Then update the fingerprint in `~/.oci/config` and re-upload
    the public key (next section).

## Upload the API Public Key

The CLI generated a key pair. Oracle needs the public half to
verify your requests.

**Copy it to clipboard:**

=== "macOS"

    ```bash
    cat ~/.oci/<key_name>_public.pem | pbcopy
    ```

=== "Linux"

    ```bash
    cat ~/.oci/<key_name>_public.pem | xclip -selection clipboard
    ```

**Upload it to Oracle:**

1. Go to [My Profile → Tokens and keys](https://cloud.oracle.com/identity/domains/my-profile/auth-tokens)
2. Under **API keys**, click **Add API key**
3. Select **Paste a public key**
4. Paste and confirm

Oracle shows a **Configuration File Preview** after uploading.
Verify the fingerprint matches what's in your `~/.oci/config`.

## Verify Authentication

```bash
oci iam user get \
  --user-id <your-user-ocid> \
  --query 'data.name' --raw-output
```

This should print your email address.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `NotAuthenticated` (401) | Fingerprint in `~/.oci/config` doesn't match Oracle — re-check or re-upload the key |
| Wrong region (e.g. `eu-frankfurt-2` instead of `eu-frankfurt-1`) | Edit `~/.oci/config` and correct the `region=` line |
| `Password was not given but private key is encrypted` | Key has a passphrase — regenerate without one (see warning above) |
| `Could not find config file` | Run `oci setup config` again |

## Config File Reference

After setup, `~/.oci/config` looks like this:

```ini
[DEFAULT]
user=ocid1.user.oc1..aaaa…
fingerprint=aa:bb:cc:dd:…
key_file=/home/<you>/.oci/<key_name>.pem
tenancy=ocid1.tenancy.oc1..aaaa…
region=eu-frankfurt-1
```

You can add named profiles (`[STAGING]`, `[PROD]`) and switch
between them with `--profile`.

## Next Steps

CLI is authenticated — proceed to [VM & Networking](vm.md) to
create an instance.
