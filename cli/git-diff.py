#!/usr/bin/env python3
"""
git-diff-tui.py — Curses-based Git branch differ TUI.

Usage:
    git-diff-tui.py [--rows N] [--cols N] [--repo PATH]

Layout:
    ┌─ SOURCE ──────────┐  ┌─ COMPARE-TO ───────┐
    │  branch list      │  │  branch list        │
    └───────────────────┘  └────────────────────-┘
    ┌─ GIT LOG (left-right oneline) ─────────────┐
    │  < sha  msg                                 │
    └─────────────────────────────────────────────┘
    [ status bar ]
"""

import curses
import os
import signal
import subprocess
import sys
import textwrap
import getopt

# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_COLS   = 100
DEFAULT_ROWS   = 20
MIN_COLS       = 60
MIN_ROWS       = 12
VERSION        = "1.0.0"

PANE_SOURCE  = 0
PANE_COMPARE = 1
PANE_LOG     = 2
PANE_NAMES   = ["SOURCE", "COMPARE-TO", "LOG"]

# Color pair IDs
CP_NORMAL    = 0   # default (no init needed)
CP_HIGHLIGHT = 1   # selected row in focused pane
CP_DIM_HL   = 2   # selected row in unfocused pane
CP_BORDER    = 3   # pane border
CP_STATUS    = 4   # status bar
CP_LEFT      = 5   # < commits (in source only)
CP_RIGHT     = 6   # > commits (in compare only)
CP_TITLE     = 7   # pane title
CP_ERROR     = 8   # error text in status bar
CP_SELECTED  = 9   # locked-in branch name

# ─── Git helpers ──────────────────────────────────────────────────────────────

def git(*args, repo=None):
    """Run a git command, return (stdout_lines, stderr, returncode)."""
    cmd = ["git"] + list(args)
    env = os.environ.copy()
    cwd = repo or os.getcwd()
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        lines = result.stdout.splitlines()
        return lines, result.stderr.strip(), result.returncode
    except FileNotFoundError:
        return [], "git not found in PATH", 1
    except subprocess.TimeoutExpired:
        return [], "git command timed out", 1
    except Exception as e:
        return [], str(e), 1


def get_branches(repo=None):
    """Return sorted list of local branch names."""
    lines, err, rc = git("branch", "--format=%(refname:short)", repo=repo)
    if rc != 0:
        return [], err
    branches = [b.strip() for b in lines if b.strip()]
    return sorted(branches), ""


def get_current_branch(repo=None):
    """Return the currently checked-out branch name."""
    lines, err, rc = git("rev-parse", "--abbrev-ref", "HEAD", repo=repo)
    if rc != 0 or not lines:
        return "HEAD"
    return lines[0].strip()


def get_log(source, compare, repo=None):
    """Run git log --left-right --oneline source...compare."""
    if not source or not compare:
        return [], ""
    lines, err, rc = git(
        "log", "--left-right", "--oneline",
        f"{source}...{compare}",
        repo=repo,
    )
    if rc != 0:
        return [], err
    return lines, ""


def get_commit_info(sha, repo=None):
    """Return lines from git show --stat for a commit hash."""
    clean_sha = sha.lstrip("<> ").split()[0]
    lines, err, rc = git("show", "--stat", "--format=fuller", clean_sha, repo=repo)
    if rc != 0:
        return [f"Error: {err}"]
    return lines


# ─── Layout calculator ────────────────────────────────────────────────────────

class Layout:
    """Computes pane geometry from total rows/cols."""

    def __init__(self, rows, cols):
        self.rows = rows
        self.cols = cols

        # Top pane heights: ~40% of total, min 4 inner rows
        top_h = max(6, rows // 2 - 1)
        bot_start = top_h
        log_h = rows - top_h - 2        # 2 = status bar + outer margin
        mid_col = cols // 2

        # Each top pane width (leave 1 col gap between them)
        left_w  = mid_col - 1
        right_w = cols - mid_col - 1

        # Pane rectangles: (top_row, left_col, height, width)
        self.source  = (0,       0,        top_h,  left_w)
        self.compare = (0,       mid_col,  top_h,  right_w)
        self.log     = (bot_start, 0,      log_h,  cols)
        self.status  = (rows - 2, 0,       1,      cols)

        # Usable inner sizes (inside borders)
        self.source_inner  = (top_h - 2,  left_w  - 2)
        self.compare_inner = (top_h - 2,  right_w - 2)
        self.log_inner     = (log_h - 2,  cols    - 2)


# ─── Scrollable list pane ─────────────────────────────────────────────────────

class ListPane:
    """A scrollable, navigable list with a highlight bar."""

    def __init__(self, items=None):
        self.items    = items or []
        self.cursor   = 0      # highlighted row index (absolute)
        self.offset   = 0      # scroll offset (first visible item)
        self.selected = None   # locked-in value (after ENTER)

    def set_items(self, items):
        self.items  = items
        self.cursor = min(self.cursor, max(0, len(items) - 1))
        self._clamp_offset(0)

    def move(self, delta, visible_rows):
        self.cursor = max(0, min(len(self.items) - 1, self.cursor + delta))
        self._scroll_to_cursor(visible_rows)

    def page(self, delta, visible_rows):
        self.move(delta * visible_rows, visible_rows)

    def current_item(self):
        if not self.items:
            return None
        return self.items[self.cursor]

    def _scroll_to_cursor(self, visible_rows):
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + visible_rows:
            self.offset = self.cursor - visible_rows + 1

    def _clamp_offset(self, visible_rows):
        max_off = max(0, len(self.items) - visible_rows)
        self.offset = min(self.offset, max_off)

    def visible_items(self, visible_rows):
        return self.items[self.offset : self.offset + visible_rows]

    def scroll_indicator(self, visible_rows):
        """Return a short scroll position string like '12/45'."""
        if not self.items:
            return ""
        return f"{self.cursor + 1}/{len(self.items)}"


# ─── Overlay for git show ──────────────────────────────────────────────────────

class Overlay:
    """Full-screen scrollable overlay for commit details."""

    def __init__(self, lines, title=""):
        self.lines  = lines
        self.title  = title
        self.offset = 0

    def scroll(self, delta, visible_rows):
        max_off = max(0, len(self.lines) - visible_rows)
        self.offset = max(0, min(max_off, self.offset + delta))

    def visible(self, visible_rows):
        return self.lines[self.offset : self.offset + visible_rows]


# ─── Main application ─────────────────────────────────────────────────────────

class App:

    def __init__(self, stdscr, rows, cols, repo):
        self.stdscr   = stdscr
        self.req_rows = rows
        self.req_cols = cols
        self.repo     = repo

        self.layout   = None
        self.active   = PANE_SOURCE
        self.overlay  = None          # active Overlay or None
        self.status   = ""
        self.error    = False

        self.source_pane  = ListPane()
        self.compare_pane = ListPane()
        self.log_pane     = ListPane()

        self._init_colors()
        self._load_branches()

    # ── Setup ──────────────────────────────────────────────────────────────────

    def _init_colors(self):
        curses.start_color()
        curses.use_default_colors()
        bg = -1  # transparent background
        curses.init_pair(CP_HIGHLIGHT, curses.COLOR_BLACK,  curses.COLOR_CYAN)
        curses.init_pair(CP_DIM_HL,   curses.COLOR_BLACK,  curses.COLOR_WHITE)
        curses.init_pair(CP_BORDER,   curses.COLOR_CYAN,   bg)
        curses.init_pair(CP_STATUS,   curses.COLOR_BLACK,  curses.COLOR_CYAN)
        curses.init_pair(CP_LEFT,     curses.COLOR_GREEN,  bg)
        curses.init_pair(CP_RIGHT,    curses.COLOR_YELLOW, bg)
        curses.init_pair(CP_TITLE,    curses.COLOR_CYAN,   bg)
        curses.init_pair(CP_ERROR,    curses.COLOR_RED,    bg)
        curses.init_pair(CP_SELECTED, curses.COLOR_GREEN,  bg)

    def _load_branches(self):
        branches, err = get_branches(self.repo)
        if err:
            self._set_status(f"Error loading branches: {err}", error=True)
            branches = []
        self.source_pane.set_items(branches)
        self.compare_pane.set_items(list(branches))

        # Pre-select current branch as source
        current = get_current_branch(self.repo)
        for i, b in enumerate(branches):
            if b == current:
                self.source_pane.cursor   = i
                self.source_pane.selected = b
                break

        if branches:
            self._set_status("Branches loaded. TAB to switch panes, ENTER to select.")
        self._refresh_log()

    def _refresh_log(self):
        src = self.source_pane.selected
        cmp = self.compare_pane.selected
        if not src or not cmp:
            self.log_pane.set_items([])
            return
        lines, err = get_log(src, cmp, self.repo)
        if err:
            self._set_status(f"git log error: {err}", error=True)
            self.log_pane.set_items([])
        else:
            self.log_pane.set_items(lines)
            count = len(lines)
            self._set_status(
                f"Diff: {src} ↔ {cmp}  |  {count} commit{'s' if count != 1 else ''}"
            )

    def _set_status(self, msg, error=False):
        self.status = msg
        self.error  = error

    # ── Geometry ───────────────────────────────────────────────────────────────

    def _compute_layout(self):
        term_rows, term_cols = self.stdscr.getmaxyx()
        rows = min(self.req_rows, term_rows)
        cols = min(self.req_cols, term_cols)
        if rows < MIN_ROWS or cols < MIN_COLS:
            raise RuntimeError(
                f"Terminal too small ({term_cols}×{term_rows}). "
                f"Need at least {MIN_COLS}×{MIN_ROWS}."
            )
        self.layout = Layout(rows, cols)

    # ── Drawing ────────────────────────────────────────────────────────────────

    def _draw_box(self, top, left, height, width, title="", focused=False):
        """Draw a rounded-corner box."""
        try:
            attr = curses.color_pair(CP_BORDER)
            if focused:
                attr |= curses.A_BOLD

            # Corners + sides
            self.stdscr.addch(top, left,               curses.ACS_ULCORNER, attr)
            self.stdscr.addch(top, left + width - 1,   curses.ACS_URCORNER, attr)
            try:
                self.stdscr.addch(top + height - 1, left,             curses.ACS_LLCORNER, attr)
            except curses.error:
                pass
            try:
                self.stdscr.addch(top + height - 1, left + width - 1, curses.ACS_LRCORNER, attr)
            except curses.error:
                pass

            for c in range(left + 1, left + width - 1):
                self.stdscr.addch(top,              c, curses.ACS_HLINE, attr)
                try:
                    self.stdscr.addch(top + height - 1, c, curses.ACS_HLINE, attr)
                except curses.error:
                    pass

            for r in range(top + 1, top + height - 1):
                try:
                    self.stdscr.addch(r, left,             curses.ACS_VLINE, attr)
                    self.stdscr.addch(r, left + width - 1, curses.ACS_VLINE, attr)
                except curses.error:
                    pass

            # Title in top border
            if title:
                title_str = f" {title} "
                tx = left + 2
                for i, ch in enumerate(title_str):
                    if tx + i >= left + width - 1:
                        break
                    self.stdscr.addch(top, tx + i, ch, attr | curses.A_BOLD)
        except curses.error:
            pass

    def _draw_list_pane(self, pane: ListPane, rect, title, focused, show_selected=True):
        top, left, height, width = rect
        inner_h, inner_w = height - 2, width - 2

        self._draw_box(top, left, height, width, title, focused)

        visible = pane.visible_items(inner_h)
        for row_i, item in enumerate(visible):
            abs_idx = pane.offset + row_i
            is_cursor = (abs_idx == pane.cursor)
            is_selected = (item == pane.selected)

            # Truncate with ellipsis
            display = item
            if len(display) > inner_w:
                display = display[:inner_w - 3] + "..."

            r = top + 1 + row_i
            c = left + 1

            if is_cursor and focused:
                attr = curses.color_pair(CP_HIGHLIGHT) | curses.A_BOLD
            elif is_cursor:
                attr = curses.color_pair(CP_DIM_HL)
            elif is_selected and show_selected:
                attr = curses.color_pair(CP_SELECTED) | curses.A_BOLD
            else:
                attr = curses.A_NORMAL

            try:
                self.stdscr.addstr(r, c, display.ljust(inner_w), attr)
            except curses.error:
                pass

        # Scroll indicator in bottom-right corner of box
        indicator = pane.scroll_indicator(inner_h)
        if indicator:
            ix = left + width - len(indicator) - 2
            try:
                self.stdscr.addstr(top + height - 1, ix, indicator,
                                   curses.color_pair(CP_BORDER))
            except curses.error:
                pass

    def _draw_log_pane(self, rect, focused):
        top, left, height, width = rect
        inner_h, inner_w = height - 2, width - 2
        pane = self.log_pane

        src = self.source_pane.selected or "?"
        cmp = self.compare_pane.selected or "?"
        title = f"LOG  {src} ↔ {cmp}"

        self._draw_box(top, left, height, width, title, focused)

        visible = pane.visible_items(inner_h)
        for row_i, item in enumerate(visible):
            abs_idx = pane.offset + row_i
            is_cursor = (abs_idx == pane.cursor)

            # Determine direction marker
            if item.startswith("<"):
                base_attr = curses.color_pair(CP_LEFT)
            elif item.startswith(">"):
                base_attr = curses.color_pair(CP_RIGHT)
            else:
                base_attr = curses.A_NORMAL

            display = item
            if len(display) > inner_w:
                display = display[:inner_w - 3] + "..."

            r = top + 1 + row_i
            c = left + 1

            if is_cursor and focused:
                attr = curses.color_pair(CP_HIGHLIGHT) | curses.A_BOLD
            elif is_cursor:
                attr = curses.color_pair(CP_DIM_HL)
            else:
                attr = base_attr

            try:
                self.stdscr.addstr(r, c, display.ljust(inner_w), attr)
            except curses.error:
                pass

        # Scroll indicator
        indicator = pane.scroll_indicator(inner_h)
        if indicator:
            ix = left + width - len(indicator) - 2
            try:
                self.stdscr.addstr(top + height - 1, ix, indicator,
                                   curses.color_pair(CP_BORDER))
            except curses.error:
                pass

    def _draw_status(self):
        ly = self.layout
        row, col, _, width = ly.status

        keys = " TAB:next-pane  ↑↓:navigate  PgUp/Dn:scroll  ENTER:select/info  ESC:quit "
        src_tag  = f" SRC:{self.source_pane.selected or '(none)'} "
        cmp_tag  = f" CMP:{self.compare_pane.selected or '(none)'} "

        # Build full status line
        right_part = src_tag + cmp_tag
        left_part  = (self.status or keys)[:width - len(right_part) - 1]
        full = left_part.ljust(width - len(right_part)) + right_part
        full = full[:width]

        attr = curses.color_pair(CP_STATUS)
        if self.error:
            attr = curses.color_pair(CP_ERROR) | curses.A_BOLD
        try:
            self.stdscr.addstr(row, col, full, attr)
        except curses.error:
            pass

    def _draw_overlay(self):
        """Draw the git-show overlay on top of everything."""
        ov = self.overlay
        rows, cols = self.stdscr.getmaxyx()
        inner_h = rows - 4
        inner_w = cols - 4
        top, left = 2, 2

        # Clear overlay area
        blank = " " * (inner_w + 2)
        for r in range(top, top + inner_h + 2):
            try:
                self.stdscr.addstr(r, left, blank)
            except curses.error:
                pass

        self._draw_box(top, left, inner_h + 2, inner_w + 2,
                       f"COMMIT INFO — {ov.title}", focused=True)

        visible = ov.visible(inner_h)
        for i, line in enumerate(visible):
            display = line[:inner_w]
            try:
                self.stdscr.addstr(top + 1 + i, left + 1, display.ljust(inner_w))
            except curses.error:
                pass

        hint = " ↑↓/PgUp/PgDn: scroll   ESC/q: close "
        try:
            self.stdscr.addstr(top + inner_h + 1, left + 2, hint,
                               curses.color_pair(CP_STATUS))
        except curses.error:
            pass

    def _redraw(self):
        self.stdscr.erase()
        try:
            self._compute_layout()
        except RuntimeError as e:
            try:
                self.stdscr.addstr(0, 0, str(e), curses.color_pair(CP_ERROR) | curses.A_BOLD)
            except curses.error:
                pass
            self.stdscr.refresh()
            return

        ly = self.layout

        src_focused  = (self.active == PANE_SOURCE)
        cmp_focused  = (self.active == PANE_COMPARE)
        log_focused  = (self.active == PANE_LOG)

        self._draw_list_pane(
            self.source_pane, ly.source,
            "SOURCE BRANCH", src_focused
        )
        self._draw_list_pane(
            self.compare_pane, ly.compare,
            "COMPARE-TO BRANCH", cmp_focused
        )
        self._draw_log_pane(ly.log, log_focused)
        self._draw_status()

        if self.overlay:
            self._draw_overlay()

        self.stdscr.refresh()

    # ── Input handling ─────────────────────────────────────────────────────────

    def _handle_overlay_key(self, key):
        ov = self.overlay
        _, cols = self.stdscr.getmaxyx()
        inner_h = self.stdscr.getmaxyx()[0] - 4
        if key in (curses.KEY_UP,    ord('k')):
            ov.scroll(-1, inner_h)
        elif key in (curses.KEY_DOWN, ord('j')):
            ov.scroll(1, inner_h)
        elif key in (curses.KEY_PPAGE,):
            ov.scroll(-inner_h, inner_h)
        elif key in (curses.KEY_NPAGE,):
            ov.scroll(inner_h, inner_h)
        elif key in (27, ord('q'), ord('\n'), curses.KEY_ENTER):
            self.overlay = None

    def _handle_key(self, key):
        # TAB — cycle pane
        if key == ord('\t'):
            self.active = (self.active + 1) % 3
            self.error = False
            return

        # ESC — quit
        if key == 27:
            return False  # signal exit

        pane = [self.source_pane, self.compare_pane, self.log_pane][self.active]
        ly   = self.layout
        visible_rows = [
            ly.source_inner[0],
            ly.compare_inner[0],
            ly.log_inner[0],
        ][self.active]

        if key in (curses.KEY_UP, ord('k')):
            pane.move(-1, visible_rows)
            self.error = False

        elif key in (curses.KEY_DOWN, ord('j')):
            pane.move(1, visible_rows)
            self.error = False

        elif key == curses.KEY_PPAGE:
            pane.page(-1, visible_rows)

        elif key == curses.KEY_NPAGE:
            pane.page(1, visible_rows)

        elif key in (curses.KEY_HOME,):
            pane.cursor = 0
            pane.offset = 0

        elif key in (curses.KEY_END,):
            pane.cursor = max(0, len(pane.items) - 1)
            pane._scroll_to_cursor(visible_rows)

        elif key in (ord('\n'), curses.KEY_ENTER, ord(' ')):
            self._handle_enter()

        return True

    def _handle_enter(self):
        if self.active == PANE_SOURCE:
            item = self.source_pane.current_item()
            if item:
                self.source_pane.selected = item
                self._set_status(f"Source branch set to: {item}")
                self._refresh_log()

        elif self.active == PANE_COMPARE:
            item = self.compare_pane.current_item()
            if item:
                self.compare_pane.selected = item
                self._set_status(f"Compare-to branch set to: {item}")
                self._refresh_log()

        elif self.active == PANE_LOG:
            item = self.log_pane.current_item()
            if item:
                # Extract SHA from log line like "< abc1234 message"
                parts = item.lstrip("<> ").split()
                if parts:
                    sha = parts[0]
                    lines = get_commit_info(sha, self.repo)
                    self.overlay = Overlay(lines, title=sha)
                    self._set_status(f"Showing commit: {sha}  (ESC to close)")

    # ── Main loop ──────────────────────────────────────────────────────────────

    def run(self):
        curses.curs_set(0)
        self.stdscr.keypad(True)
        self.stdscr.timeout(200)

        # Handle SIGWINCH (terminal resize)
        def _resize_handler(sig, frame):
            curses.endwin()
            self.stdscr.refresh()

        signal.signal(signal.SIGWINCH, _resize_handler)

        while True:
            try:
                self._redraw()
                key = self.stdscr.getch()

                if key == curses.ERR:
                    continue

                if self.overlay:
                    self._handle_overlay_key(key)
                    continue

                result = self._handle_key(key)
                if result is False:
                    break

            except KeyboardInterrupt:
                break
            except curses.error:
                # Ignore transient curses errors (e.g. resize race)
                pass


# ─── Entry point ──────────────────────────────────────────────────────────────

def usage():
    print(__doc__)
    print("Options:")
    print("  --rows N       Requested TUI height (default 20)")
    print("  --cols N       Requested TUI width  (default 100)")
    print("  --repo PATH    Git repository path  (default: CWD)")
    print("  --help         Show this message")


def main():
    rows = DEFAULT_ROWS
    cols = DEFAULT_COLS
    repo = None

    try:
        opts, _ = getopt.getopt(sys.argv[1:], "h", ["rows=", "cols=", "repo=", "help"])
    except getopt.GetoptError as e:
        print(f"Error: {e}", file=sys.stderr)
        usage()
        sys.exit(1)

    for opt, val in opts:
        if opt in ("-h", "--help"):
            usage()
            sys.exit(0)
        elif opt == "--rows":
            try:
                rows = int(val)
            except ValueError:
                print(f"--rows must be an integer, got: {val}", file=sys.stderr)
                sys.exit(1)
        elif opt == "--cols":
            try:
                cols = int(val)
            except ValueError:
                print(f"--cols must be an integer, got: {val}", file=sys.stderr)
                sys.exit(1)
        elif opt == "--repo":
            repo = os.path.abspath(val)
            if not os.path.isdir(repo):
                print(f"--repo path does not exist: {repo}", file=sys.stderr)
                sys.exit(1)

    # Verify git repo
    target = repo or os.getcwd()
    _, err, rc = git("rev-parse", "--git-dir", repo=target)
    if rc != 0:
        print(f"Not a git repository: {target}", file=sys.stderr)
        sys.exit(1)

    # Patch sys.excepthook to restore terminal before printing traceback
    _original_excepthook = sys.excepthook
    def _safe_excepthook(etype, value, tb):
        try:
            curses.endwin()
        except Exception:
            pass
        _original_excepthook(etype, value, tb)
    sys.excepthook = _safe_excepthook

    def _run(stdscr):
        app = App(stdscr, rows, cols, repo=target)
        app.run()

    try:
        curses.wrapper(_run)
    except RuntimeError as e:
        # Terminal too small or other fatal setup error
        print(f"Fatal: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        # curses.wrapper already called endwin on exception
        print(f"Unexpected error: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()