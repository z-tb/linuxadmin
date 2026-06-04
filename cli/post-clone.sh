#!/bin/bash
# ==============================================================================
# Ubuntu 24.04 Post-Clone Configuration Script (with Bridge Support)
# ==============================================================================

set -e
export SYSTEMD_LOG_LEVEL=emerg

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

CUR_DNS=$(grep -h -A 2 "nameservers:" /etc/netplan/*.y*ml 2>/dev/null | grep -oE '([0-9]{1,3}\.){3}[0-9]{1,3}' | sort -u | tr '\n' ',' | sed 's/,$//')
[[ -z "$CUR_DNS" ]] && CUR_DNS="8.8.8.8,1.1.1.1"

CUR_SEARCH=$(grep -h -E '^\s*search:\s*\[' /etc/netplan/*.y*ml 2>/dev/null \
    | grep -oP '(?<=\[)[^\]]+' \
    | tr -d ' ' \
    | head -1)
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

# SSH
echo -ne "${MAGENTA}Regenerate SSH Host Keys? ${NC}[y/n, default: n]${MAGENTA}: ${NC}"
read REGEN_SSH
REGEN_SSH=${REGEN_SSH:-n}

# Global DNS
echo -ne "${MAGENTA}Global DNS (comma separated) ${NC}[$CUR_DNS]${MAGENTA}: ${NC}"
read NEW_DNS
NEW_DNS=${NEW_DNS:-$CUR_DNS}

# Search domains
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

# ------------------------------------------------------------------------------
# BRIDGE DEFINITION
# ------------------------------------------------------------------------------

declare -A BRIDGE_CONFIGS   # BRIDGE_CONFIGS[brname]="DHCP|STP_BOOL|FWD_DELAY"
#                             or              "IP/CIDR|GW_BOOL|STP_BOOL|FWD_DELAY"
declare -a BRIDGE_ORDER     # ordered list of bridge names for deterministic output

echo ""
echo -e "${CYAN}--- Bridge Interfaces ---${NC}"
echo -ne "${MAGENTA}Define any bridge interfaces (e.g. br0, virbr0)? ${NC}[y/n, default: n]${MAGENTA}: ${NC}"
read DEFINE_BRIDGES
DEFINE_BRIDGES=${DEFINE_BRIDGES:-n}

BRIDGE_GW_ASSIGNED=false

if [[ "$DEFINE_BRIDGES" =~ ^[Yy]$ ]]; then
    while true; do
        echo -ne "${MAGENTA}Bridge interface name ${NC}(e.g. br0, leave blank to finish)${MAGENTA}: ${NC}"
        read BR_NAME
        [[ -z "$BR_NAME" ]] && break

        # Validate name (letters, digits, hyphen - no spaces)
        if [[ ! "$BR_NAME" =~ ^[a-zA-Z][a-zA-Z0-9_-]*$ ]]; then
            echo -e "${RED}Invalid interface name. Use letters, digits, underscores, hyphens.${NC}"
            continue
        fi

        # Duplicate check
        if [[ -n "${BRIDGE_CONFIGS[$BR_NAME]+_}" ]]; then
            echo -e "${RED}Bridge '$BR_NAME' already defined.${NC}"
            continue
        fi

        echo -e "${CYAN}--- Bridge: $BR_NAME ---${NC}"

        # STP
        echo -ne "${MAGENTA}  Enable STP on $BR_NAME? ${NC}[y/n, default: n]${MAGENTA}: ${NC}"
        read BR_STP
        BR_STP=${BR_STP:-n}
        BR_STP_BOOL="false"
        [[ "$BR_STP" =~ ^[Yy]$ ]] && BR_STP_BOOL="true"

        # Forward delay (only relevant when STP enabled, but netplan accepts it either way)
        BR_FWD_DELAY=4
        if [[ "$BR_STP" =~ ^[Yy]$ ]]; then
            echo -ne "${MAGENTA}  STP forward delay (seconds) ${NC}[default: 4]${MAGENTA}: ${NC}"
            read BR_FWD_INPUT
            if [[ "$BR_FWD_INPUT" =~ ^[0-9]+$ ]]; then
                BR_FWD_DELAY=$BR_FWD_INPUT
            fi
        fi

        # IP config for the bridge itself
        DEF_DHCP_BR="n"
        echo -ne "${MAGENTA}  Use DHCP for $BR_NAME? ${NC}[y/n, default: n]${MAGENTA}: ${NC}"
        read BR_DHCP
        BR_DHCP=${BR_DHCP:-$DEF_DHCP_BR}

        if [[ "$BR_DHCP" =~ ^[Yy]$ ]]; then
            BRIDGE_CONFIGS["$BR_NAME"]="DHCP|${BR_STP_BOOL}|${BR_FWD_DELAY}"
        else
            VALID_IP=false
            while [ "$VALID_IP" = false ]; do
                echo -ne "${MAGENTA}  IP/CIDR for $BR_NAME ${NC}(leave blank for no IP)${MAGENTA}: ${NC}"
                read BR_IP
                if [[ -z "$BR_IP" ]]; then
                    VALID_IP=true
                elif [[ $BR_IP =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]]; then
                    VALID_IP=true
                else
                    echo -e "${RED}    Invalid CIDR.${NC}"
                fi
            done

            BR_APPLY_GW="n"
            if [[ -n "$BR_IP" ]] && [ "$BRIDGE_GW_ASSIGNED" = false ]; then
                echo -ne "${MAGENTA}  Set $BR_NAME as primary interface for Gateway ($NEW_GW)? ${NC}[y/n, default: n]${MAGENTA}: ${NC}"
                read BR_ATTEMPT_GW
                BR_APPLY_GW=${BR_ATTEMPT_GW:-n}
                [[ "$BR_APPLY_GW" =~ ^[Yy]$ ]] && BRIDGE_GW_ASSIGNED=true
            fi

            BRIDGE_CONFIGS["$BR_NAME"]="${BR_IP}|${BR_APPLY_GW}|${BR_STP_BOOL}|${BR_FWD_DELAY}"
        fi

        BRIDGE_ORDER+=("$BR_NAME")
        echo -e "${GREEN}  Bridge $BR_NAME defined.${NC}"
    done
fi

# ------------------------------------------------------------------------------
# ETHERNET INTERFACE COLLECTION
# ------------------------------------------------------------------------------

INTERFACES=$(ls /sys/class/net | grep -E '^(enp|eth|eno)')
GW_ASSIGNED=$BRIDGE_GW_ASSIGNED   # inherits any GW claim made by a bridge
declare -A IF_CONFIGS
# Values:
#   "DHCP"                     - dhcp4: true, no IP
#   "IP/CIDR|GW_BOOL"         - static IP, optional gateway
#   "BRIDGE_MEMBER|<brname>"  - enslaved to a bridge; no IP on this interface

for IFACE in $INTERFACES; do
    echo ""
    echo -e "${CYAN}--- Interface: $IFACE ---${NC}"
    CUR_IP=$(ip -4 addr show "$IFACE" | grep -oP '(?<=inet\s)\d+(\.\d+){3}/\d+' | head -n1)
    echo -e "  Current IP: ${YELLOW}${CUR_IP:-<none>}${NC}"

    # Determine bridge membership options to display
    BR_NAMES_LIST=""
    if [[ ${#BRIDGE_ORDER[@]} -gt 0 ]]; then
        BR_NAMES_LIST=" | bridge member: ${BRIDGE_ORDER[*]}"
    fi

    DEF_DHCP=$([[ -z "$CUR_IP" ]] && echo "y" || echo "n")

    echo -ne "${MAGENTA}  Config for $IFACE [dhcp/static/bridge${BR_NAMES_LIST:+ ($BR_NAMES_LIST)}] ${NC}[default: $( [[ "$DEF_DHCP" == "y" ]] && echo "dhcp" || echo "static")]${MAGENTA}: ${NC}"
    read IFACE_MODE
    IFACE_MODE=${IFACE_MODE:-$( [[ "$DEF_DHCP" == "y" ]] && echo "dhcp" || echo "static")}
    IFACE_MODE_LC="${IFACE_MODE,,}"  # lowercase

    if [[ "$IFACE_MODE_LC" == "dhcp" ]]; then
        IF_CONFIGS["$IFACE"]="DHCP"

    elif [[ "$IFACE_MODE_LC" == "bridge" ]]; then
        # Must have at least one bridge defined
        if [[ ${#BRIDGE_ORDER[@]} -eq 0 ]]; then
            echo -e "${RED}  No bridges defined. Falling back to static config.${NC}"
            # Fall through to static path
            IFACE_MODE_LC="static"
        else
            # If only one bridge, use it; otherwise ask
            if [[ ${#BRIDGE_ORDER[@]} -eq 1 ]]; then
                CHOSEN_BR="${BRIDGE_ORDER[0]}"
                echo -e "  ${YELLOW}Assigning $IFACE as member of $CHOSEN_BR${NC}"
            else
                VALID_BR=false
                while [ "$VALID_BR" = false ]; do
                    echo -ne "${MAGENTA}  Which bridge? ${NC}[${BRIDGE_ORDER[*]}]${MAGENTA}: ${NC}"
                    read CHOSEN_BR
                    if [[ -n "${BRIDGE_CONFIGS[$CHOSEN_BR]+_}" ]]; then
                        VALID_BR=true
                    else
                        echo -e "${RED}  Unknown bridge '$CHOSEN_BR'. Choose from: ${BRIDGE_ORDER[*]}${NC}"
                    fi
                done
            fi
            IF_CONFIGS["$IFACE"]="BRIDGE_MEMBER|${CHOSEN_BR}"
        fi
    fi

    # Static path (also used as fallback from failed bridge selection)
    if [[ "$IFACE_MODE_LC" == "static" ]]; then
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
# STAGE 2: GENERATE NETPLAN + PREVIEW
# ------------------------------------------------------------------------------

TMP_NETPLAN=$(mktemp)

cat <<EOF > "$TMP_NETPLAN"
network:
  version: 2
  renderer: networkd
  ethernets:
EOF

# -- Ethernet entries --
for IFACE in "${!IF_CONFIGS[@]}"; do
    VAL="${IF_CONFIGS[$IFACE]}"

    if [ "$VAL" == "DHCP" ]; then
        echo "    $IFACE: { dhcp4: true }" >> "$TMP_NETPLAN"

    elif [[ "$VAL" == BRIDGE_MEMBER* ]]; then
        BR_TARGET="${VAL#BRIDGE_MEMBER|}"
        cat <<EOF >> "$TMP_NETPLAN"
    $IFACE:
      dhcp4: false
EOF

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

# -- Bridge entries (only if any defined) --
if [[ ${#BRIDGE_ORDER[@]} -gt 0 ]]; then
    echo "  bridges:" >> "$TMP_NETPLAN"

    for BR_NAME in "${BRIDGE_ORDER[@]}"; do
        BR_VAL="${BRIDGE_CONFIGS[$BR_NAME]}"

        # Collect member interfaces for this bridge
        BR_MEMBERS=()
        for IFACE in "${!IF_CONFIGS[@]}"; do
            IFACE_VAL="${IF_CONFIGS[$IFACE]}"
            if [[ "$IFACE_VAL" == "BRIDGE_MEMBER|${BR_NAME}" ]]; then
                BR_MEMBERS+=("$IFACE")
            fi
        done

        cat <<EOF >> "$TMP_NETPLAN"
    $BR_NAME:
EOF

        # Member interfaces list (may be empty if bridge has no enslaved NICs yet)
        if [[ ${#BR_MEMBERS[@]} -gt 0 ]]; then
            MEMBERS_CSV=$(printf '%s,' "${BR_MEMBERS[@]}" | sed 's/,$//')
            echo "      interfaces: [$MEMBERS_CSV]" >> "$TMP_NETPLAN"
        fi

        if [[ "$BR_VAL" == DHCP* ]]; then
            IFS='|' read -r _ BR_STP BR_FWD <<< "$BR_VAL"
            cat <<EOF >> "$TMP_NETPLAN"
      dhcp4: true
      parameters:
        stp: $BR_STP
        forward-delay: $BR_FWD
EOF

        else
            # Static or no-IP
            IFS='|' read -r BR_ADDR BR_GW_BOOL BR_STP BR_FWD <<< "$BR_VAL"

            if [[ -n "$BR_ADDR" ]]; then
                cat <<EOF >> "$TMP_NETPLAN"
      addresses: [$BR_ADDR]
      nameservers:
        addresses: [${NEW_DNS}]
EOF
                if [[ -n "$NEW_SEARCH" ]]; then
                    echo "        search: [$NEW_SEARCH]" >> "$TMP_NETPLAN"
                fi
                if [[ "$BR_GW_BOOL" =~ ^[Yy]$ ]]; then
                    cat <<EOF >> "$TMP_NETPLAN"
      routes:
        - to: default
          via: $NEW_GW
EOF
                fi
            else
                echo "      dhcp4: false" >> "$TMP_NETPLAN"
            fi

            cat <<EOF >> "$TMP_NETPLAN"
      parameters:
        stp: $BR_STP
        forward-delay: $BR_FWD
EOF
        fi
    done
fi

# -- Preview --
echo -e "\n${CYAN}>>> PROPOSED CHANGES <<<${NC}"
echo -e "Hostname:   $NEW_HOSTNAME"
echo -e "Regen SSH:  $REGEN_SSH"
echo -e "Search:     ${NEW_SEARCH:-<none>}"

if [[ ${#BRIDGE_ORDER[@]} -gt 0 ]]; then
    echo -e "Bridges:    ${BRIDGE_ORDER[*]}"
    for BR_NAME in "${BRIDGE_ORDER[@]}"; do
        BR_MEMBERS=()
        for IFACE in "${!IF_CONFIGS[@]}"; do
            [[ "${IF_CONFIGS[$IFACE]}" == "BRIDGE_MEMBER|${BR_NAME}" ]] && BR_MEMBERS+=("$IFACE")
        done
        echo -e "  $BR_NAME members: ${BR_MEMBERS[*]:-<none>}"
    done
fi

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

rm -f /run/netplan/*.yaml
(sleep 2; netplan apply) &

echo -e "${GREEN}>>> Done! <<<${NC}"
hostnamectl 2>/dev/null
ip -br addr show | grep -v "::1/128" | grep -v "fe80::" 2>/dev/null

echo -ne "\n${MAGENTA}Reboot now? ${NC}[y/n, default: n]${MAGENTA}: ${NC}"
read REBOOT_NOW
[[ "$REBOOT_NOW" =~ ^[Yy]$ ]] && reboot || echo -e "${YELLOW}Manual reboot recommended to finish ID regeneration.${NC}"
