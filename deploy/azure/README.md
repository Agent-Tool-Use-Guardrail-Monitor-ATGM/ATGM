# Running ATGM on Azure

**Owner:** Áron · One Ubuntu VM runs the same Docker Compose stack as on a laptop: Kafka, PostgreSQL, Grafana, DSPOT, ACI, review queue, storage sink, Online Isolation Forest and the mock agents. No managed services, so the cost is just the VM, while it runs.

Everything is in two files:

- `cloud-init.yaml`: what the VM does at its first boot. It installs Docker, clones the `development` branch to `/opt/atgm`, writes `.env` with **random passwords that never leave the VM**, and starts the stack with `--profile mocks`.
- `atgm-azure.sh`: create, start, stop, connect, delete.

## Prerequisites

- Azure CLI, logged in (`az login`), with the Azure for Students subscription. Check with `./atgm-azure.sh check`.
- An SSH key at `~/.ssh/id_ed25519.pub`. If you don't have one: `ssh-keygen -t ed25519`.
- Git Bash on Windows, or any Linux/macOS shell. Run the commands from `deploy/azure/`.

## Typical session

```bash
cd deploy/azure
./atgm-azure.sh create     # once: VM + first-boot setup (~10-15 min until the stack runs)
./atgm-azure.sh ready      # shows the containers when the setup is done
./atgm-azure.sh tunnel     # keep open; then http://localhost:8080 (kafka-ui), http://localhost:3000 (Grafana)
./atgm-azure.sh password   # Grafana admin password (user: admin)
./atgm-azure.sh stop       # ALWAYS when done: deallocates the VM, compute billing stops

./atgm-azure.sh start      # next time; the services start by themselves
./atgm-azure.sh update     # after merging new code: git pull + rebuild on the VM
./atgm-azure.sh delete     # at the end of the project: removes everything, no further cost
```

`./atgm-azure.sh` without a command lists all commands.

## Security

- **Only SSH (port 22) is open, and only from your own IP.** `create` and `start` set this; if your IP changes (other Wi-Fi), run `./atgm-azure.sh allow-my-ip`.
- **All service ports are bound to `127.0.0.1` on the VM** (see `docker-compose.yml`). kafka-ui, Grafana, Kafka and PostgreSQL are reached only through the SSH tunnel.
- Passwords are generated on the VM (`/opt/atgm/.env`, readable only by `azureuser`). Nothing secret is in this folder.

## Cost on the student credit

| Item | When it costs | Roughly |
|---|---|---|
| VM `Standard_B2ms` (2 vCPU, 8 GB) | only while running | ~$0.08–0.10 per hour |
| 64 GB Standard SSD disk | always, until deleted | a few $ per month |
| Standard public IP | always, until deleted | a few $ per month |

Prices are approximate; check the [Azure pricing calculator](https://azure.microsoft.com/pricing/calculator/) for UK South.

- **"Shut down" inside Linux does not stop billing; `./atgm-azure.sh stop` (deallocate) does.**
- **Safety net:** the VM shuts itself down every day at 20:00 UTC (set by `create`; change it with `SHUTDOWN_UTC=2200 ./atgm-azure.sh create`).
- **Budget alert:** in the Azure portal, open Cost Management → Budgets → Add. Set e.g. $40 with alerts at 50% and 90% to your e-mail.
- **When the project is graded: `./atgm-azure.sh delete`**, which removes the disk and IP too.

## Settings

Override with environment variables before a command, e.g. `LOCATION=swedencentral SIZE=Standard_D2s_v5 ./atgm-azure.sh create`.

| Variable | Default | Notes |
|---|---|---|
| `RG` | `atgm-rg` | resource group holding everything |
| `LOCATION` | `uksouth` | student subscriptions allow only some regions (West Europe was refused); if refused, try another, e.g. `swedencentral` |
| `VM` | `atgm-vm` | VM name |
| `SIZE` | `Standard_B2ms` | if unavailable, `Standard_D2s_v5` (also 8 GB, a bit more expensive) |
| `SSH_KEY` | `~/.ssh/id_ed25519.pub` | public key for login |
| `SHUTDOWN_UTC` | `2000` | daily automatic shutdown time (UTC, HHMM) |

## Troubleshooting

- **`ready` keeps saying "still setting up":** `./atgm-azure.sh ssh`, then `sudo tail -f /var/log/cloud-init-output.log` to watch the installation.
- **The SSH connection times out:** your IP probably changed, so run `./atgm-azure.sh allow-my-ip`. Also check that the VM is running (`./atgm-azure.sh status`).
- **The mock agents keep producing data while the VM runs.** To pause them: `./atgm-azure.sh ssh`, then `cd /opt/atgm && docker compose --profile mocks stop mock-agents`.
