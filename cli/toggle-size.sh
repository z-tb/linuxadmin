#!/usr/bin/env bash
# toggle-size.sh — Toggle active window between saved geometry and maximized state.
# Version: 2.0 | License: MIT
# Dependencies: xdotool, wmctrl, xprop

set -euo pipefail

CACHE_DIR="${HOME}/.cache/toggle-size"
mkdir -p "$CACHE_DIR"

# ---------------------------------------------------------------------------
# Helper: print to stderr and exit silently (no dialog popups)
# ---------------------------------------------------------------------------
die() { echo "[toggle-size] $*" >&2; exit 0; }

# ---------------------------------------------------------------------------
# 1. Get active window ID
# ---------------------------------------------------------------------------
WIN_ID=$(xdotool getactivewindow 2>/dev/null) || die "No active window"
[[ -z "$WIN_ID" ]] && die "No active window"

# ---------------------------------------------------------------------------
# 2. Get window class for per-app storage
#    xdotool getwindowclassname returns the class (e.g. "Firefox", "Code")
# ---------------------------------------------------------------------------
CLASS=$(xdotool getwindowclassname "$WIN_ID" 2>/dev/null) || CLASS="unknown"
[[ -z "$CLASS" ]] && CLASS="unknown"

# Sanitize: keep only alphanumeric + dot, replace everything else with _
CLASS_SAFE=$(echo "$CLASS" | tr -cs '[:alnum:].' '_')

GEO_FILE="${CACHE_DIR}/${CLASS_SAFE}.geo"

# ---------------------------------------------------------------------------
# 3. Detect maximized state via xprop
# ---------------------------------------------------------------------------
WM_STATE=$(xprop -id "$WIN_ID" _NET_WM_STATE 2>/dev/null) || WM_STATE=""

is_maximized() {
  echo "$WM_STATE" | grep -q "_NET_WM_STATE_MAXIMIZED"
}

# ---------------------------------------------------------------------------
# 4. Toggle logic
# ---------------------------------------------------------------------------
if is_maximized; then
  # --- RESTORE ---
  [[ ! -f "$GEO_FILE" ]] && die "No saved geometry for '$CLASS_SAFE' — nothing to restore"

  read -r GX GY GW GH _ < "$GEO_FILE" 2>/dev/null \
    || die "Could not read .geo file: $GEO_FILE"

  [[ -z "$GX$GY$GW$GH" ]] && die "Empty .geo file: $GEO_FILE"

  for val in "$GX" "$GY" "$GW" "$GH"; do
    [[ "$val" =~ ^-?[0-9]+$ ]] || die "Non-integer value in .geo file: $GEO_FILE"
  done

  # Un-maximize, wait for WM to release control, then restore geometry
  wmctrl -ir "$WIN_ID" -b remove,maximized_vert,maximized_horz
  sleep 0.1
  xdotool windowmove "$WIN_ID" "$GX" "$GY"
  xdotool windowsize "$WIN_ID" "$GW" "$GH"

else
  # --- SAVE + MAXIMIZE ---

  # xdotool getwindowgeometry --shell emits: X=, Y=, WIDTH=, HEIGHT=, SCREEN=
  eval "$(xdotool getwindowgeometry --shell "$WIN_ID" 2>/dev/null)" \
    || die "Could not read geometry for window $WIN_ID"

  [[ -z "${X:-}${Y:-}${WIDTH:-}${HEIGHT:-}" ]] \
    && die "xdotool returned empty geometry for window $WIN_ID"

  echo "$X $Y $WIDTH $HEIGHT" > "$GEO_FILE"
  echo "[toggle-size] Saved geometry for '$CLASS_SAFE': $X $Y $WIDTH $HEIGHT" >&2

  wmctrl -ir "$WIN_ID" -b add,maximized_vert,maximized_horz
fi
