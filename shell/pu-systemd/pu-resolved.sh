#!/bin/bash

CYAN='\033[0;36m' RED='\033[0;31m' YELLOW='\033[1;33m' GREEN='\033[0;32m' NC='\033[0m'

info()  { echo -e "${CYAN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
success(){ echo -e "${GREEN}[OK]${NC} $1"; }

if [[ $EUID -ne 0 ]]; then error "Run as root (sudo)"; exit 1; fi

UNDO=false
[[ "$1" == "-u" ]] && UNDO=true

CHATTR_SUPPORTED=0

detect_chattr() {
    touch /etc/.chattr_test 2>/dev/null || return
    if chattr +i /etc/.chattr_test 2>/dev/null; then
        chattr -i /etc/.chattr_test 2>/dev/null
        CHATTR_SUPPORTED=1
    fi
    rm -f /etc/.chattr_test
}

set_immutable() {
    [[ $CHATTR_SUPPORTED -eq 1 ]] || return 1
    chattr +i /etc/resolv.conf 2>/dev/null
}

clear_immutable() {
    [[ $CHATTR_SUPPORTED -eq 1 ]] || return 0
    chattr -i /etc/resolv.conf 2>/dev/null || true
}

ensure_regular_resolv() {
    if [[ -L /etc/resolv.conf ]]; then
        rm -f /etc/resolv.conf
    fi
    touch /etc/resolv.conf
}

update_resolv() {
    clear_immutable
    ensure_regular_resolv

    local default_search="localdomain"
    local detected_domain
    detected_domain=$(hostname -d 2>/dev/null)
    [[ -n "$detected_domain" ]] && default_search="$detected_domain"

    read -rp "Enter search domain [${default_search}]: " user_search
    local search_domain="${user_search:-$default_search}"

    info "Using search domain: ${search_domain}"

    cat > /etc/resolv.conf << EOF
nameserver 8.8.8.8
nameserver 8.8.4.4
nameserver 1.1.1.1
search ${search_domain}
options edns0 trust-ad
EOF

    sync

    if set_immutable; then
        success "resolv.conf immutable"
    else
        warn "resolv.conf mutable"
    fi
}

verify_disable() {
    local status=0
    info "=== VERIFICATION ==="

    [[ -f /etc/resolv.conf ]] || { error "resolv.conf missing"; status=1; }

    grep -q "^nameserver 8.8.8.8" /etc/resolv.conf \
        && success "resolv.conf static" \
        || { error "resolv.conf not static"; status=1; }

    if [[ $CHATTR_SUPPORTED -eq 1 ]]; then
        lsattr /etc/resolv.conf 2>/dev/null | grep -q 'i' \
            && success "resolv.conf immutable" \
            || { error "resolv.conf not immutable"; status=1; }
    else
        warn "skip immutable check"
    fi

    systemctl is-enabled systemd-resolved 2>/dev/null | grep -q "disabled" \
        && success "systemd-resolved disabled" \
        || { error "systemd-resolved not disabled"; status=1; }

    ! systemctl is-active --quiet systemd-resolved 2>/dev/null \
        && success "systemd-resolved inactive" \
        || { error "systemd-resolved still active"; status=1; }

    nslookup google.com >/dev/null 2>&1 \
        && success "DNS working" \
        || { error "DNS failed"; status=1; }

    return $status
}

detect_chattr

if [[ $UNDO == false ]]; then
    info "Disabling systemd-resolved..."

    systemctl stop systemd-resolved >/dev/null 2>&1 || true
    systemctl disable systemd-resolved || { error "Disable failed"; exit 1; }

    update_resolv

    systemctl restart docker >/dev/null 2>&1 \
        && success "Docker restarted" \
        || warn "Docker skip"

    verify_disable \
        && success "✓ Perfect!" \
        || { error "✗ Failed verification"; exit 1; }

else
    info "Undo: Re-enabling systemd-resolved..."

    clear_immutable

    systemctl enable --now systemd-resolved || { error "Enable failed"; exit 1; }

    rm -f /etc/resolv.conf
    ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf

    systemctl restart docker >/dev/null 2>&1 \
        && success "Docker restarted" \
        || warn "Docker skip"

    success "✓ Undo complete"
fi

info "Status: cat /etc/resolv.conf; systemctl status systemd-resolved --no-pager -l"
