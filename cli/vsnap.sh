#!/bin/bash
################################################################################
# Script Name: update-cluster-snapshots.sh
# Purpose:     Automates KVM/libvirt snapshot lifecycle management across a
#              multi-node cluster. Dynamically aggregates unique snapshot
#              baselines, presents an interactive selection menu, and
#              performs a safe "Delete-and-Recreate" routine to update the
#              selected snapshot target to the current live state of all nodes.
#
# Target VMs:  cdd-ntest01, cdd-ntest02, cdd-ntest03
# Runtime Req: Must be run as root or with sudo to interface with libvirt.
# Workflow:
#   1. Scans designated cluster VMs via 'virsh' to build a distinct list of
#      existing snapshots.
#   2. Prompts user with an interactive menu to choose an existing baseline
#      to update or roll a fresh new snapshot.
#   3. Gathers user description metadata.
#   4. Iterates through the cluster nodes to clear out stale snapshot points
#      and capture the current live system state (including active memory blocks).
################################################################################

# Exit immediately if a command exits with a non-zero status
set -e

VMS=("test01" "test02" "test03")

echo "================================================================="
echo "                  Cluster Snapshot Automation                    "
echo "================================================================="
echo

# Gather all unique snapshot names from the cluster nodes
echo "Scanning cluster nodes for existing snapshots..."
AVAILABLE_SNAPSHOTS=()

# ------------------------------------------------------------------------------
# Loops through each VM, run 'virsh snapshot-list', and strip out formatting 
# headers to construct a unique, deduplicated array of all available snapshot names.
# ------------------------------------------------------------------------------
for VM in "${VMS[@]}"; do
    if virsh dominfo "$VM" >/dev/null 2>&1; then
        # Fetch snapshot names, skipping the header lines
        while IFS= read -r line; do
            SNAPSHOT=$(echo "$line" | awk '{print $1}')
            if [ -n "$SNAPSHOT" ] && [[ ! "$SNAPSHOT" =~ ^(-+|Name)$ ]]; then
                # Add to array if not already present
                if [[ ! " ${AVAILABLE_SNAPSHOTS[@]} " =~ " ${SNAPSHOT} " ]]; then
                    AVAILABLE_SNAPSHOTS+=("$SNAPSHOT")
                fi
            fi
        done < <(virsh snapshot-list "$VM" 2>/dev/null)
    fi
done

# ------------------------------------------------------------------------------
# Use the bash 'select' built-in to generate a numbered list. Give the operator
# the choice to overwrite an existing snapshot branch or initialize a completely new one.
# ------------------------------------------------------------------------------
echo
echo "Select the snapshot target to update or create:"
echo "--------------------------------------------------------"
OPTIONS=("New snapshot" "${AVAILABLE_SNAPSHOTS[@]}")

select OPT in "${OPTIONS[@]}"; do
    if [ "$OPT" = "New snapshot" ]; then
        read -r -p "Enter name for the new snapshot: " SNAPSHOT_NAME
        # Sanitize name input (remove spaces)
        SNAPSHOT_NAME=$(echo "$SNAPSHOT_NAME" | tr -d ' ')
        if [ -z "$SNAPSHOT_NAME" ]; then
            echo "❌ Error: Snapshot name cannot be empty."
            exit 1
        fi
        break
    elif [ -n "$OPT" ]; then
        SNAPSHOT_NAME="$OPT"
        break
    else
        echo "Invalid selection. Please enter a valid number."
    fi
done

echo "--------------------------------------------------------"
echo "Targeting Snapshot Name: '$SNAPSHOT_NAME'"
echo

# ------------------------------------------------------------------------------
# Prompt the for notes/context. Fall back to a descriptive default layout 
# if left blank so the snapshot history remains readable.
# ------------------------------------------------------------------------------
echo "Enter a description for the snapshots:"
read -r -p "Description: " SNAPSHOT_DESC

if [ -z "$SNAPSHOT_DESC" ]; then
    SNAPSHOT_DESC="Automated baseline update matching current IP/cluster state."
fi

echo
echo "Proceeding with description: \"$SNAPSHOT_DESC\""
echo "================================================================="
echo

# ------------------------------------------------------------------------------
# Iterate over all target domains, delete existing metadata points if matching, 
# and cut a fresh snapshot of the system's active runtime and storage layers.
# ------------------------------------------------------------------------------
for VM in "${VMS[@]}"; do
    echo "Processing node: $VM..."

    if ! virsh dominfo "$VM" >/dev/null 2>&1; then
        echo "❌ Error: Virtual machine '$VM' not found. Skipping."
        echo "-----------------------------------------------------------------"
        continue
    fi

    # Check if this specific VM has this snapshot before attempting deletion
    if virsh snapshot-info "$VM" --snapshotname "$SNAPSHOT_NAME" >/dev/null 2>&1; then
        echo "   -> Found existing '$SNAPSHOT_NAME' on $VM. Deleting old metadata..."
        virsh snapshot-delete "$VM" --snapshotname "$SNAPSHOT_NAME"
    else
        echo "   -> Snapshot '$SNAPSHOT_NAME' does not exist on $VM yet. Creating fresh..."
    fi

    echo "   -> Capturing new snapshot state..."
    virsh snapshot-create-as "$VM" \
        --name "$SNAPSHOT_NAME" \
        --description "$SNAPSHOT_DESC"
    
    echo "   ✅ Successfully processed '$SNAPSHOT_NAME' on $VM"
    echo "-----------------------------------------------------------------"
done

echo "🎉 All target snapshots have been synchronized successfully!"
echo

