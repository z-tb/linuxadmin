#!/bin/bash

# pu-resolvd.sh - Professional systemd-resolved disable/enable
# Clean idempotent version with proper immutable handling

# Colors (unchanged)
CYAN='\033[0;36m' RED='\033[0;31m' YELLOW='\033[1;33m' GREEN='\033[0;32m' NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
success(){ echo -e "${GREEN}[OK]${NC} $1"; }

if [[ $EUID -ne 0 ]]; then error "Run as root (sudo)"; exit 1; fi

UNDO=false
[[ "$1" == "-u" ]] && UNDO=true

update_resolv() {
    # Always make mutable first, then update
    chattr -i /etc/resolv.conf 2>/dev/null || true
    cat > /etc/resolv.conf << EOF
nameserver 8.8.8.8
nameserver 8.8.4.4
nameserver 1.1.1.1
search $(hostname -d 2>/dev/null || echo "localdomain")
options edns0 trust-ad
EOF
    sync
    chattr +i /etc/resolv.conf
    success "Static resolv.conf updated (immutable)"
}

verify_disable() {
    local status=0
    info "=== VERIFICATION ==="
    [[ ! -L /etc/resolv.conf && -f /etc/resolv.conf && $(grep -c "8.8.8.8" /etc/resolv.conf) -eq 1 ]] || { error "resolv.conf not static/Google DNS"; status=1; } || success "resolv.conf static/Google DNS"
    lsattr /etc/resolv.conf 2>/dev/null | grep -q 'i' || { error "resolv.conf not immutable"; status=1; } || success "resolv.conf immutable"
    systemctl is-enabled systemd-resolved 2>/dev/null | grep -q "disabled" || { error "systemd-resolved not disabled"; status=1; } || success "systemd-resolved disabled"
    ! systemctl is-active --quiet systemd-resolved 2>/dev/null || { error "systemd-resolved still active"; status=1; } || success "systemd-resolved inactive"
    nslookup google.com >/dev/null 2>&1 || { error "DNS failed (google.com)"; status=1; } || success "DNS working"
    return $status
}

if [[ $UNDO == false ]]; then
    info "Disabling systemd-resolved..."
    systemctl stop systemd-resolved >/dev/null 2>&1 || true
    systemctl disable systemd-resolved || { error "Disable failed"; exit 1; }
    update_resolv
    systemctl restart docker >/dev/null 2>&1 && success "Docker restarted" || warn "Docker skip"
    verify_disable && success "✓ Perfect!" || { error "✗ Failed verification"; exit 1; }
    
else
    info "Undo: Re-enabling systemd-resolved..."
    chattr -i /etc/resolv.conf 2>/dev/null || true
    systemctl enable --now systemd-resolved || { error "Enable failed"; exit 1; }
    rm -f /etc/resolv.conf
    ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf
    systemctl restart docker >/dev/null 2>&1 && success "Docker restarted" || warn "Docker skip"
    success "✓ Undo complete"
fi

info "Status: cat /etc/resolv.conf; systemctl status systemd-resolved --no-pager -l"
