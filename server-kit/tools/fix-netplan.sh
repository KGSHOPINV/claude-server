#!/usr/bin/env bash
# fix-netplan.sh — detect and resolve cloud-init netplan conflict
# Run as root. Safe to call from install.sh or standalone.
#
# Problem: cloud-init writes /etc/netplan/50-cloud-init.yaml and re-generates it
# on every boot, overwriting any manual netplan config. This script disables that
# behaviour and removes the conflicting file so your own netplan YAML takes effect.

set -euo pipefail

CLOUD_INIT_NETPLAN="/etc/netplan/50-cloud-init.yaml"
CLOUD_INIT_DISABLE_DIR="/etc/cloud/cloud.cfg.d"
CLOUD_INIT_DISABLE_FILE="${CLOUD_INIT_DISABLE_DIR}/99-disable-network-config.cfg"

fix_netplan_conflict() {
    if [ ! -f "${CLOUD_INIT_NETPLAN}" ]; then
        echo "fix-netplan: ${CLOUD_INIT_NETPLAN} not found — nothing to do."
        return 0
    fi

    echo "fix-netplan: cloud-init netplan conflict detected."

    # Disable cloud-init network management
    mkdir -p "${CLOUD_INIT_DISABLE_DIR}"
    cat > "${CLOUD_INIT_DISABLE_FILE}" <<'EOF'
# Prevent cloud-init from managing network config.
# Written by fix-netplan.sh — do not edit by hand.
network: {config: disabled}
EOF
    echo "fix-netplan: wrote ${CLOUD_INIT_DISABLE_FILE}"

    # Remove the conflicting file
    rm -f "${CLOUD_INIT_NETPLAN}"
    echo "fix-netplan: removed ${CLOUD_INIT_NETPLAN}"

    # Apply netplan so any remaining YAML files take effect
    netplan apply
    echo "fix-netplan: netplan apply done."
}

# Run if called directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [ "$(id -u)" -ne 0 ]; then
        echo "fix-netplan: must be run as root." >&2
        exit 1
    fi
    fix_netplan_conflict
fi
