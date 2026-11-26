#!/usr/bin/env bash
# ATGM on Azure: one VM running the Docker Compose stack.  Usage: ./atgm-azure.sh <command>
#
#   check        show the Azure account and subscription in use
#   create       create the VM (first boot installs and starts everything, ~10-15 min)
#   status       power state and public IP
#   ready        has the first-boot setup finished? (lists the containers when it has)
#   start        start the VM again (billing for compute starts)
#   stop         deallocate the VM: compute billing stops (disk and IP cost a little)
#   allow-my-ip  allow SSH only from your current IP (run again if your IP changed)
#   ssh          open a shell on the VM
#   tunnel       forward kafka-ui :8080, Grafana :3000 and Kafka :29092 to this PC
#   password     print the Grafana admin password (stored only on the VM)
#   update       git pull on the VM and rebuild/restart the services
#   delete       delete EVERYTHING (resource group): no more cost at all
#
# Settings can be overridden with environment variables, e.g. LOCATION=swedencentral ./atgm-azure.sh create
set -euo pipefail

RG="${RG:-atgm-rg}"
LOCATION="${LOCATION:-uksouth}"            # Azure for Students allows only some regions
VM="${VM:-atgm-vm}"
SIZE="${SIZE:-Standard_B2ms}"                    # 2 vCPU, 8 GB RAM
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519.pub}"
SHUTDOWN_UTC="${SHUTDOWN_UTC:-2000}"            # automatic shutdown every day at 20:00 UTC (21:00 CET)
USER_NAME="azureuser"
# Only "type key" from the public key file is sent: the comment at its end (user@computer) may
# contain non-ASCII letters (e.g. "Á"), which the Azure CLI on Windows cannot read.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ip() { az vm show -d -g "$RG" -n "$VM" --query publicIps -o tsv; }
my_ip() { curl -s https://api.ipify.org; }
remote() { ssh -o StrictHostKeyChecking=accept-new "$USER_NAME@$(ip)" "$@"; }

allow_my_ip() {
  local mine; mine="$(my_ip)"
  az network nsg rule update -g "$RG" --nsg-name "${VM}NSG" -n default-allow-ssh \
    --source-address-prefixes "$mine/32" -o none
  echo "SSH allowed only from $mine"
}

case "${1:-}" in
  check)
    az account show --query "{subscription:name, user:user.name, state:state}" -o table ;;
  create)
    [ -f "$SSH_KEY" ] || { echo "No SSH public key at $SSH_KEY (create one: ssh-keygen -t ed25519)"; exit 1; }
    az group create -n "$RG" -l "$LOCATION" -o none
    cd "$HERE"
    az vm create -g "$RG" -n "$VM" -l "$LOCATION" --image Ubuntu2404 --size "$SIZE" \
      --admin-username "$USER_NAME" --ssh-key-values "$(cut -d' ' -f1,2 "$SSH_KEY")" \
      --custom-data cloud-init.yaml --os-disk-size-gb 64 --storage-sku StandardSSD_LRS \
      --public-ip-sku Standard --nsg-rule SSH -o none
    allow_my_ip
    az vm auto-shutdown -g "$RG" -n "$VM" --time "$SHUTDOWN_UTC" -o none
    echo "VM created at $(ip). First-boot setup takes ~10-15 min; check with: $0 ready"
    echo "It shuts down automatically every day at ${SHUTDOWN_UTC} UTC. Stop it yourself with: $0 stop" ;;
  status)
    az vm show -d -g "$RG" -n "$VM" --query "{state:powerState, ip:publicIps, size:hardwareProfile.vmSize}" -o table ;;
  ready)
    if remote test -f /opt/atgm/.cloud-init-done; then
      remote "cd /opt/atgm && docker compose --profile mocks ps --format 'table {{.Service}}\t{{.Status}}'"
    else
      echo "Still setting up (cloud-init). Progress: $0 ssh, then: sudo tail -f /var/log/cloud-init-output.log"
    fi ;;
  start)
    az vm start -g "$RG" -n "$VM" -o none; allow_my_ip
    echo "Running at $(ip); the services start by themselves within a minute or two." ;;
  stop)
    az vm deallocate -g "$RG" -n "$VM" -o none; echo "Deallocated: compute billing stopped." ;;
  allow-my-ip) allow_my_ip ;;
  ssh) remote ;;
  tunnel)
    echo "Open http://localhost:8080 (kafka-ui) and http://localhost:3000 (Grafana); Kafka at localhost:29092."
    echo "Keep this window open; Ctrl+C closes the tunnel."
    ssh -N -o StrictHostKeyChecking=accept-new -L 8080:localhost:8080 -L 3000:localhost:3000 \
      -L 29092:localhost:29092 "$USER_NAME@$(ip)" ;;
  password)
    remote "grep '^GRAFANA_ADMIN_PASSWORD=' /opt/atgm/.env | cut -d= -f2" ;;
  update)
    remote "cd /opt/atgm && git pull && docker compose --profile mocks up -d --build" ;;
  delete)
    read -r -p "Delete resource group $RG and EVERYTHING in it? Type yes: " answer
    [ "$answer" = "yes" ] && az group delete -n "$RG" --yes --no-wait && echo "Deleting in the background." ;;
  *)
    sed -n '2,17p' "$0"; exit 1 ;;
esac
