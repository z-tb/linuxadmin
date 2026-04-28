#!/usr/bin/env bash
# resize-active-window.sh
#
# Resizes the focused window by cycling through width presets on each
# invocation: 1/3 -> 2/5 -> 1/2 -> full -> 1/3 ...
# Intended to be bound to a desktop hotkey (e.g. Cinnamon F1).
#
# Positioning:
#   - Partial widths stay centered on the window's current titlebar center.
#   - Full width pins to monitor edges with margins.
#   - If resizing would push the window off-screen, it is clamped to
#     stay within monitor bounds.
#   - Height is always top-anchored with Y margin and taskbar offset.
#
# State is stored per WM_CLASS in ~/.resize-window/ so the cycle
# position persists across window close/reopen for the same application.
#
# Environment overrides: X_MARGIN, Y_MARGIN, TASKBAR_OFFSET
# Requires: xdotool, xprop, xrandr, wmctrl

set -euo pipefail

X_MARGIN="${X_MARGIN:-10}"
Y_MARGIN="${Y_MARGIN:-30}"
TASKBAR_OFFSET="${TASKBAR_OFFSET:-60}"
STATE_DIR="$HOME/.resize-window"

# width fractions: 1/3, 2/5, 1/2, full (numerator/denominator pairs)
STEPS=(3 5 2 1)
DIVISORS=(1 2 1 1)

WIN_ID="$(xdotool getactivewindow)"
WM_CLASS="$(xprop -id "$WIN_ID" WM_CLASS | sed -n 's/.*"\(.*\)".*/\1/p')"

# get window geometry
eval "$(xdotool getwindowgeometry --shell "$WIN_ID")"
# X, Y, WIDTH, HEIGHT

# titlebar center X for positioning and monitor detection
CENTER_X=$(( X + WIDTH / 2 ))
CENTER_Y=$(( Y + 20 ))

# find which monitor contains the titlebar center
while read -r line; do
    if [[ "$line" =~ connected ]]; then
        if [[ "$line" =~ ([0-9]+)x([0-9]+)\+([0-9]+)\+([0-9]+) ]]; then
            MW="${BASH_REMATCH[1]}"
            MH="${BASH_REMATCH[2]}"
            MX="${BASH_REMATCH[3]}"
            MY="${BASH_REMATCH[4]}"

            if (( CENTER_X >= MX && CENTER_X < MX + MW && CENTER_Y >= MY && CENTER_Y < MY + MH )); then
                break
            fi
        fi
    fi
done < <(xrandr --query)

: "${MW:?monitor width not found}"
: "${MH:?monitor height not found}"

# read current step and advance (first run starts at step 0)
mkdir -p "$STATE_DIR"
STATE_FILE="$STATE_DIR/$WM_CLASS"
STEP=0
if [[ -f "$STATE_FILE" ]]; then
    STEP="$(cat "$STATE_FILE")"
    # validate
    if ! [[ "$STEP" =~ ^[0-9]+$ ]]; then
        STEP=0
    fi
    STEP=$(( (STEP + 1) % 4 ))
fi
printf '%d' "$STEP" > "$STATE_FILE"

# compute width: full uses monitor width, others use fraction
NUM="${DIVISORS[$STEP]}"
DEN="${STEPS[$STEP]}"
if (( DEN == 1 )); then
    NEW_W=$(( MW - 2 * X_MARGIN ))
else
    NEW_W=$(( MW * NUM / DEN - 2 * X_MARGIN ))
fi

# height: top-anchored with Y margin and taskbar offset
NEW_H=$(( MH - 2 * Y_MARGIN - TASKBAR_OFFSET ))

# clamp minimums
(( NEW_W < 100 )) && NEW_W=100
(( NEW_H < 100 )) && NEW_H=100

# X position: full width pins to margin, partial stays centered on titlebar
if (( DEN == 1 )); then
    NEW_X=$(( MX + X_MARGIN ))
else
    NEW_X=$(( CENTER_X - NEW_W / 2 ))
fi
NEW_Y=$(( MY + Y_MARGIN ))

# clamp X to keep window within monitor bounds
MIN_X=$(( MX + X_MARGIN ))
MAX_X=$(( MX + MW - NEW_W - X_MARGIN ))
(( NEW_X < MIN_X )) && NEW_X=$MIN_X
(( NEW_X > MAX_X )) && NEW_X=$MAX_X

# clear maximized state so wmctrl geometry takes effect
wmctrl -i -r "$WIN_ID" -b remove,maximized_vert,maximized_horz || true

# apply new geometry
wmctrl -i -r "$WIN_ID" -e "0,$NEW_X,$NEW_Y,$NEW_W,$NEW_H"
