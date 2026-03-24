#!/bin/bash
# ==============================================================================
# Ubuntu 24.04 Post-Clone Configuration Script (Final - SSH-Safe)
# ==============================================================================

set -e
export SYSTEMD_LOG_LEVEL=emerg # Silence systemd noise globally

# --- ANSI Color Scheme ---
NC='\033[0m'
CYAN='\033[0;36m'   
YELLOW='\033[1;33m' 
GREEN='\033[0;32m'  
RED='\033[0;31m'    
MAGENTA='\033[0;35m' 

echo -e "${CYAN}>>> Ubuntu 24.04 VM Clone Setup (Transactional) <<<${NC}"

# 1. Root Check
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}✗ Error: This script must be run as root.${NC}"
   exit 1
fi

# ------------------------------------------------------------------------------
# STAGE 0: PRE-DISCOVERY (DNS Scrape)
# ------------------------------------------------------------------------------

# Attempt to find existing DNS from current Netplan files before moving them
CUR_DNS=$(grep -h -A 2 "nameservers:" /etc/netplan/*.y*ml 2>/dev/null | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | sort -u | tr '\n' ',' | sed 's/,$//')

# Fallback if discovery fails
[[ -z "$CUR_DNS" ]] && CUR_DNS="8.8.8.8,1.1.1.1"

# Scrape existing search domains - targets the search: key directly
# Handles flow style:  search: [home.local, corp.example.com]
CUR_SEARCH=$(grep -h -E '^\s*search:\s*\[' /etc/netplan/*.y*ml 2>/dev/null \
    | grep -oP '(?<=\[)[^\]]+' \
    | tr -d ' ' \
    | head -1)
# Also handle block-style list entries under search:
if [[ -z "$CUR_SEARCH" ]]; then
    CUR_SEARCH=$(awk '/^\s*search:/{f=1;next} f&&/^\s*-\s+\S/{gsub(/^\s*-\s+/,"");printf "%s,",$0;next} f{exit}' \
        /etc/netplan/*.y*ml 2>/dev/null | sed 's/,$//')
fi

# ------------------------------------------------------------------------------
# STAGE 1: DATA COLLECTION
# ------------------------------------------------------------------------------

# Hostname
CUR_HOSTNAME=$(hostname)
echo -ne "${MAGENTA}Enter new hostname ${NC}[default: $CUR_HOSTNAME]${MAGENTA}: ${NC}"
read NEW_HOSTNAME
NEW_HOSTNAME=${NEW_HOSTNAME:-$CUR_HOSTNAME}

# SSH - Updated Default to 'n'
echo -ne "${MAGENTA}Regenerate SSH Host Keys? ${NC}[y/n, default: n]${MAGENTA}: ${NC}"
read REGEN_SSH
REGEN_SSH=${REGEN_SSH:-n}

# Global DNS
echo -ne "${MAGENTA}Global DNS (comma separated) ${NC}[$CUR_DNS]${MAGENTA}: ${NC}"
read NEW_DNS
NEW_DNS=${NEW_DNS:-$CUR_DNS}

# Search domains - enter accepts existing value, 'none' explicitly clears it
_search_display="${CUR_SEARCH:-none}"
echo -ne "${MAGENTA}Search domains (comma-separated, 'none' to clear) ${NC}[$_search_display]${MAGENTA}: ${NC}"
read NEW_SEARCH
if [[ "$NEW_SEARCH" == "none" ]]; then
    NEW_SEARCH=""
else
    NEW_SEARCH=${NEW_SEARCH:-$CUR_SEARCH}
fi

# Default Gateway
CUR_GW=$(ip route | grep default | awk '{print $3}' | head -n1)
VALID_GW=false
while [ "$VALID_GW" = false ]; do
    echo -ne "${MAGENTA}System Default Gateway IP ${NC}[$CUR_GW]${MAGENTA}: ${NC}"
    read NEW_GW
    NEW_GW=${NEW_GW:-$CUR_GW}
    [[ $NEW_GW =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] && VALID_GW=true || echo -e "${RED}Invalid IP format.${NC}"
done

INTERFACES=$(ls /sys/class/net | grep -E '^(enp|eth|eno)')
GW_ASSIGNED=false 
declare -A IF_CONFIGS

for IFACE in $INTERFACES; do
    echo -e "${CYAN}--- Interface: $IFACE ---${NC}"
    CUR_IP=$(ip -4 addr show "$IFACE" | grep -oP '(?<=inet\s)\d+(\.\d+){3}/\d+' | head -n1)
    echo -e "  Current IP: ${YELLOW}${CUR_IP:-<none>}${NC}"

    DEF_DHCP=$([[ -z "$CUR_IP" ]] && echo "y" || echo "n")
    echo -ne "${MAGENTA}  Use DHCP for $IFACE? ${NC}[y/n, default: $DEF_DHCP]${MAGENTA}: ${NC}"
    read USE_DHCP
    USE_DHCP=${USE_DHCP:-$DEF_DHCP}

    if [[ "$USE_DHCP" =~ ^[Yy]$ ]]; then
        IF_CONFIGS["$IFACE"]="DHCP"
    else
        # Static IP
        VALID_IP=false
        while [ "$VALID_IP" = false ]; do
            echo -ne "${MAGENTA}  IP/CIDR for $IFACE ${NC}[$CUR_IP]${MAGENTA}: ${NC}"
            read NEW_IP
            NEW_IP=${NEW_IP:-$CUR_IP}
            [[ $NEW_IP =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]] && VALID_IP=true || echo -e "${RED}    Invalid CIDR.${NC}"
        done
        
        APPLY_GW="n"
        if [ "$GW_ASSIGNED" = false ]; then
            echo -ne "${MAGENTA}  Set $IFACE as primary NIC for Gateway ($NEW_GW)? ${NC}[y/n, default: y]${MAGENTA}: ${NC}"
            read ATTEMPT_GW
            APPLY_GW=${ATTEMPT_GW:-y}
            [[ "$APPLY_GW" =~ ^[Yy]$ ]] && GW_ASSIGNED=true
        fi
        IF_CONFIGS["$IFACE"]="$NEW_IP|$APPLY_GW"
    fi
done

# ------------------------------------------------------------------------------
# STAGE 2: PREVIEW
# ------------------------------------------------------------------------------

TMP_NETPLAN=$(mktemp)
cat <<EOF > "$TMP_NETPLAN"
network:
  version: 2
  renderer: networkd
  ethernets:
EOF

for IFACE in "${!IF_CONFIGS[@]}"; do
    VAL="${IF_CONFIGS[$IFACE]}"
    if [ "$VAL" == "DHCP" ]; then
        echo "    $IFACE: { dhcp4: true }" >> "$TMP_NETPLAN"
    else
        IFS='|' read -r ADDR GW_BOOL <<< "$VAL"
        cat <<EOF >> "$TMP_NETPLAN"
    $IFACE:
      addresses: [$ADDR]
      nameservers:
        addresses: [${NEW_DNS}]
EOF
        if [[ -n "$NEW_SEARCH" ]]; then
            echo "        search: [$NEW_SEARCH]" >> "$TMP_NETPLAN"
        fi
        if [[ "$GW_BOOL" =~ ^[Yy]$ ]]; then
            cat <<EOF >> "$TMP_NETPLAN"
      routes:
        - to: default
          via: $NEW_GW
EOF
        fi
    fi
done

echo -e "\n${CYAN}>>> PROPOSED CHANGES <<<${NC}"
echo -e "Hostname:   $NEW_HOSTNAME"
echo -e "Regen SSH:  $REGEN_SSH"
echo -e "Search:     ${NEW_SEARCH:-<none>}"
echo -e "Netplan Config Preview:"
cat "$TMP_NETPLAN"
echo ""

echo -ne "${MAGENTA}Apply all changes now? ${NC}[y/n]${MAGENTA}: ${NC}"
read FINAL_CONFIRM
if [[ ! "$FINAL_CONFIRM" =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Aborted. No system changes made.${NC}"
    rm "$TMP_NETPLAN"
    exit 0
fi

# ------------------------------------------------------------------------------
# STAGE 3: EXECUTION
# ------------------------------------------------------------------------------

# Hostname
hostnamectl set-hostname "$NEW_HOSTNAME" 2>/dev/null
sed -i "s/127.0.1.1.*/127.0.1.1 $NEW_HOSTNAME/g" /etc/hosts

# SSH/Machine-ID
if [[ "$REGEN_SSH" =~ ^[Yy]$ ]]; then
    rm -f /etc/ssh/ssh_host_*_key*
    dpkg-reconfigure -fnoninteractive openssh-server >/dev/null 2>&1
    systemctl restart ssh
fi

truncate -s 0 /etc/machine-id
[ -f /var/lib/dbus/machine-id ] && truncate -s 0 /var/lib/dbus/machine-id

# Netplan Transaction
BACKUP_DIR="/etc/netplan.backup/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
find /etc/netplan -maxdepth 1 -type f \( -iname "*.yaml" -o -iname "*.yml" \) -print0 | while IFS= read -r -d '' plan; do
    mv "$plan" "$BACKUP_DIR/"
    echo -e "${YELLOW}  -> Archived $(basename "$plan")${NC}"
done

mv "$TMP_NETPLAN" /etc/netplan/01-netcfg-multi.yaml
chmod 600 /etc/netplan/01-netcfg-multi.yaml

# Final Network Apply
netplan generate 2>/dev/null
echo -e "${YELLOW}Finalizing Network...${NC}"
echo -e "${RED}WARNING: If the IP of this interface changed, SSH will disconnect now.${NC}"

# Clear stale generated configs before applying
rm -f /run/netplan/*.yaml

# Background the apply so the script can finish and SSH can close cleanly
(sleep 2; netplan apply) &

echo -e "${GREEN}>>> Done! <<<${NC}"
hostnamectl 2>/dev/null
ip -br addr show | grep -v "::1/128" | grep -v "fe80::" 2>/dev/null

echo -ne "\n${MAGENTA}Reboot now? ${NC}[y/n, default: n]${MAGENTA}: ${NC}"
read REBOOT_NOW
[[ "$REBOOT_NOW" =~ ^[Yy]$ ]] && reboot || echo -e "${YELLOW}Manual reboot recommended to finish ID regeneration.${NC}"

