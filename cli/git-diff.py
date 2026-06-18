#!/usr/bin/env python3
"""
git-diff-tui.py — Professional curses-based Git branch differ TUI.

Usage:
    git-diff-tui.py [--rows N] [--cols N] [--help]

  --rows N    Cap TUI height  (default: use full terminal height)
  --cols N    Cap TUI width   (default: use full terminal width)
  --help      Show this help

Keys:
  TAB           Cycle focus: SOURCE → COMPARE-TO → LOG
  ↑ / ↓  k/j   Move highlight bar
  PgUp / PgDn   Scroll by page
  Home / End    Jump to first / last item
  ENTER / Space Lock branch selection; open commit details dialog in log
  d             (in dialog) Toggle full diff view on/off
  q / ESC       Close dialog / quit app
"""

# ── ESC delay fix — set BEFORE curses.initscr() is called ────────────────────
# ncurses defaults ESCDELAY to 1000ms waiting for escape-sequence continuations.
# 25ms is imperceptibly short yet still avoids misreading arrow keys.
import os
os.environ['ESCDELAY'] = '25'

import curses
import getopt
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ─── Sizing constants ─────────────────────────────────────────────────────────

MIN_COLS   = 62
MIN_ROWS   = 14
TOP_RATIO  = 0.38   # branch panes take this fraction of total height
TOP_MIN_H  = 6      # min height for branch panes (inc. border)
LOG_MIN_H  = 5      # min height for log pane (inc. border)
TAG_WIDTH  = 18     # fixed width of branch tag column in log lines
SHA_WIDTH  = 8      # fixed width of SHA column in log lines

# ─── Pane identifiers ─────────────────────────────────────────────────────────

PANE_SOURCE  = 0
PANE_COMPARE = 1
PANE_LOG     = 2

# ─── 256-color pair IDs ───────────────────────────────────────────────────────

CP_HL_FOCUS       =  1   # highlight bar — focused pane
CP_HL_BLUR        =  2   # highlight bar — unfocused pane
CP_BORDER_FOCUS   =  3   # box border — active
CP_BORDER_BLUR    =  4   # box border — inactive
CP_STATUS_BAR     =  5   # status/hint bar
CP_ERROR          =  6   # error text
CP_LOCAL_BRANCH   =  7   # local branch name
CP_REMOTE_BRANCH  =  8   # remote branch name
CP_CURRENT_BRANCH =  9   # HEAD branch (● prefix)
CP_LOCKED_BRANCH  = 10   # branch locked via ENTER
CP_TAG_SRC        = 11   # ◀ tag in log (source commits)
CP_TAG_CMP        = 12   # ▶ tag in log (compare commits)
CP_SHA            = 13   # commit SHA in log
CP_PANE_TITLE     = 14   # pane title inside border
CP_DLG_SECTION    = 15   # ── Section ── header in dialog
CP_DLG_LABEL      = 16   # field label (Author:, Date:, …)
CP_DLG_VALUE      = 17   # field value
CP_DLG_SHA        = 18   # full SHA in dialog header
CP_DIFF_ADD       = 19   # + lines in diff
CP_DIFF_DEL       = 20   # - lines in diff
CP_DIFF_HUNK      = 21   # @@ hunk headers
CP_DIFF_META      = 22   # diff --git … index … lines
CP_SCROLL_IND     = 23   # scroll position indicator
CP_STAT_ADD       = 24   # A — added files
CP_STAT_MOD       = 25   # M — modified files
CP_STAT_DEL       = 26   # D — deleted files
CP_CONFLICT       = 27   # ⚠ merge conflict warning in status bar
CP_CLEAN          = 28   # ✓ clean merge indicator in status bar

# ─── Data types ───────────────────────────────────────────────────────────────

@dataclass
class BranchItem:
    short:      str   # display/selection name (refname:short)
    is_remote:  bool
    is_current: bool  # True if HEAD points here
    remote:     str = ""  # remote alias (e.g. "origin")


@dataclass
class LogEntry:
    raw:       str
    direction: str   # 'left' = source-only  |  'right' = compare-only
    sha:       str
    message:   str


@dataclass
class CommitInfo:
    sha:          str = ""
    parents:      str = ""
    author:       str = ""
    author_date:  str = ""
    committer:    str = ""
    commit_date:  str = ""
    subject:      str = ""
    body:         str = ""
    files:        List[Tuple[str, str]] = field(default_factory=list)
    diff_lines:   List[str]             = field(default_factory=list)
    diff_loaded:  bool = False
    error:        str = ""


# ─── Git helpers ──────────────────────────────────────────────────────────────

def _git(*args, repo: Optional[str] = None) -> Tuple[List[str], str, int]:
    """Run a git command. Returns (stdout_lines, stderr, returncode)."""
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=repo or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=20,
        )
        return r.stdout.splitlines(), r.stderr.strip(), r.returncode
    except FileNotFoundError:
        return [], "git not found in PATH", 1
    except subprocess.TimeoutExpired:
        return [], "git timed out (20s)", 1
    except Exception as exc:
        return [], str(exc), 1


def load_branches(repo: Optional[str] = None) -> Tuple[List[BranchItem], str]:
    """Return (locals alphabetical) + (remotes alphabetical), skipping HEAD refs."""
    lines, err, rc = _git(
        "branch", "-a",
        "--format=%(refname)|%(refname:short)|%(HEAD)",
        repo=repo,
    )
    if rc != 0:
        return [], err

    locals_: List[BranchItem]  = []
    remotes_: List[BranchItem] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 3:
            continue
        fullref, short, head_marker = parts
        is_current = (head_marker == "*")
        is_remote  = fullref.startswith("refs/remotes/")
        remote     = ""

        if is_remote:
            tail   = fullref[len("refs/remotes/"):]
            remote = tail.split("/")[0]
            # Skip symrefs (origin/HEAD) and bare remote-namespace entries ("origin")
            if short.endswith("/HEAD") or "/" not in short:
                continue

        item = BranchItem(short=short, is_remote=is_remote,
                          is_current=is_current, remote=remote)
        (remotes_ if is_remote else locals_).append(item)

    locals_.sort(key=lambda b: b.short)
    remotes_.sort(key=lambda b: b.short)
    return locals_ + remotes_, ""


def current_branch(repo: Optional[str] = None) -> str:
    lines, _, rc = _git("rev-parse", "--abbrev-ref", "HEAD", repo=repo)
    return lines[0].strip() if rc == 0 and lines else "HEAD"


def load_log(src: str, cmp: str,
             repo: Optional[str] = None) -> Tuple[List[LogEntry], str]:
    lines, err, rc = _git(
        "log", "--left-right", "--oneline",
        f"{src}...{cmp}",
        repo=repo,
    )
    if rc != 0:
        return [], err

    entries: List[LogEntry] = []
    for line in lines:
        if not line:
            continue
        direction = "left" if line[0] == "<" else "right"
        rest  = line[2:].strip()
        parts = rest.split(" ", 1)
        sha   = parts[0] if parts else "?"
        msg   = parts[1] if len(parts) > 1 else ""
        entries.append(LogEntry(raw=line, direction=direction, sha=sha, message=msg))
    return entries, ""


def load_commit_info(sha: str, repo: Optional[str] = None) -> CommitInfo:
    """Fetch structured commit metadata + changed-file list."""
    SEP = "\x02"   # ASCII STX — safe separator unlikely in commit text
    fmt = SEP.join(["%H", "%P", "%an <%ae>", "%ad", "%cn <%ce>", "%cd", "%s", "%b"])

    lines, err, rc = _git(
        "show",
        f"--format={fmt}",
        "--date=format:%Y-%m-%d %H:%M:%S %z",
        "--name-status",
        "--no-patch",
        sha,
        repo=repo,
    )
    if rc != 0:
        return CommitInfo(sha=sha, error=err)

    # First non-empty line is the format block
    raw_fmt = ""
    body_start = 0
    for i, ln in enumerate(lines):
        if ln.strip():
            raw_fmt    = ln.strip()
            body_start = i + 1
            break

    fields = raw_fmt.split(SEP)

    def _f(idx: int) -> str:
        return fields[idx].strip() if idx < len(fields) else ""

    info = CommitInfo(
        sha         = _f(0),
        parents     = _f(1),
        author      = _f(2),
        author_date = _f(3),
        committer   = _f(4),
        commit_date = _f(5),
        subject     = _f(6),
        body        = _f(7),
    )

    # Parse name-status lines (M/A/D/R + path)
    for ln in lines[body_start:]:
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.split("\t", 1)
        if len(parts) == 2:
            status, path = parts
            info.files.append((status.strip(), path.strip()))
        else:
            info.files.append(("?", ln))

    return info


def load_commit_diff(sha: str, repo: Optional[str] = None) -> List[str]:
    lines, _, rc = _git("show", "--format=", "-p", sha, repo=repo)
    if rc != 0:
        return [f"[error loading diff for {sha}]"]
    return [ln for ln in lines if ln]


def detect_conflicts(src: str, cmp: str,
                     repo: Optional[str] = None) -> Tuple[bool, str]:
    """
    Dry-run merge to check if merging `cmp` into `src` would produce conflicts.
    Returns (has_conflicts, description).

    Strategy:
      1. Try `git merge-tree --write-tree src cmp`  (git ≥ 2.38, cleanest approach).
         Exit 0 = clean, exit 1 = conflicts.
      2. Fall back to classic 3-way `git merge-tree <base> src cmp` and scan for
         conflict markers.  Works on older git but is less structured.
    Does NOT touch the working tree or index in either case.
    """
    # ── Try modern merge-tree (git 2.38+) ────────────────────────────────────
    lines, err, rc = _git(
        "merge-tree", "--write-tree",
        "--no-messages",   # suppress noise
        src, cmp,
        repo=repo,
    )
    if rc == 0:
        return False, ""
    if rc == 1:
        # Conflict details come on stdout as path lines; summarise first few
        conflict_paths = [ln.strip() for ln in lines if ln.strip()][:4]
        detail = ", ".join(conflict_paths) if conflict_paths else "conflicts detected"
        return True, detail

    # rc == 129 or other: flag not supported — fall back to classic merge-tree
    base_lines, _, base_rc = _git("merge-base", src, cmp, repo=repo)
    if base_rc != 0 or not base_lines:
        return False, ""   # Can't determine — stay silent

    base = base_lines[0].strip()
    mt_lines, _, mt_rc = _git("merge-tree", base, src, cmp, repo=repo)
    if mt_rc != 0:
        return False, ""

    has_conflict = any(
        ln.startswith("<<<<<<<") or "CONFLICT" in ln
        for ln in mt_lines
    )
    if has_conflict:
        # Extract file names from CONFLICT lines if present
        paths = [
            ln.split()[-1] for ln in mt_lines
            if "CONFLICT" in ln and ln.split()
        ][:4]
        detail = ", ".join(paths) if paths else "conflict markers detected"
        return True, detail
    return False, ""


# ─── Layout ───────────────────────────────────────────────────────────────────

class Layout:
    """
    Computes all pane rectangles from effective (rows, cols).
    Scales proportionally so larger terminals give more content rows.
    All rects: (top, left, height, width).
    """

    def __init__(self, rows: int, cols: int):
        self.rows = rows
        self.cols = cols

        # Proportional top-section height, floored at minimum
        top_h = max(TOP_MIN_H, round(rows * TOP_RATIO))
        log_h = max(LOG_MIN_H, rows - top_h - 1)   # -1 for status bar
        # Safety clamp
        if top_h + log_h + 1 > rows:
            log_h = rows - top_h - 1

        mid = cols // 2

        self.source  = (0,     0,   top_h, mid)
        self.compare = (0,     mid, top_h, cols - mid)
        self.log     = (top_h, 0,   log_h, cols)
        self.status  = (rows - 1, 0, 1,   cols)

        # Usable inner rows/cols (inside box borders)
        self.src_ih = top_h - 2;  self.src_iw = mid - 2
        self.cmp_ih = top_h - 2;  self.cmp_iw = cols - mid - 2
        self.log_ih = log_h - 2;  self.log_iw = cols - 2

        # Log column widths
        self.log_tag_w = min(TAG_WIDTH, self.log_iw // 4)
        self.log_sha_w = SHA_WIDTH
        self.log_msg_w = max(0, self.log_iw - self.log_tag_w - self.log_sha_w - 2)


# ─── Scrollable list ──────────────────────────────────────────────────────────

class ListPane:
    def __init__(self):
        self.items:  list              = []
        self.cursor: int               = 0
        self.offset: int               = 0
        self.locked: Optional[object]  = None  # item locked via ENTER

    def set_items(self, items: list):
        self.items  = items
        self.cursor = min(self.cursor, max(0, len(items) - 1))
        self.offset = 0

    def move(self, delta: int, vis: int):
        self.cursor = max(0, min(len(self.items) - 1, self.cursor + delta))
        self._scroll_to(vis)

    def page(self, direction: int, vis: int):
        self.move(direction * max(1, vis - 1), vis)

    def jump_home(self):
        self.cursor = 0
        self.offset = 0

    def jump_end(self, vis: int):
        self.cursor = max(0, len(self.items) - 1)
        self._scroll_to(vis)

    def current(self) -> Optional[object]:
        return self.items[self.cursor] if self.items else None

    def visible(self, vis: int) -> list:
        return self.items[self.offset : self.offset + vis]

    def scroll_pos(self) -> str:
        return f"{self.cursor + 1}/{len(self.items)}" if self.items else ""

    def _scroll_to(self, vis: int):
        if self.cursor < self.offset:
            self.offset = self.cursor
        elif self.cursor >= self.offset + vis:
            self.offset = self.cursor - vis + 1


# ─── Commit details dialog ────────────────────────────────────────────────────

class CommitDialog:
    """
    Full-screen overlay with structured commit details.
    Scrollable; 'd' toggles diff; ESC/q closes.
    """

    def __init__(self, info: CommitInfo):
        self.info       = info
        self.offset     = 0
        self.show_diff  = False
        self._lines: List[Tuple[str, int]] = []   # (text, color_pair_id)
        self._build()

    # ── Line builder ──────────────────────────────────────────────────────────

    def _build(self):
        info   = self.info
        lines: List[Tuple[str, int]] = []

        def sec(title: str):
            lines.append(("", 0))
            lines.append((f"  ── {title} {'─' * 50}", CP_DLG_SECTION))

        def kv(key: str, val: str, val_cp: int = CP_DLG_VALUE):
            # Store as a compound tuple: label in col 0, value in col 16
            lines.append((f"  {key:<16}{val}", CP_DLG_LABEL))

        def blank():
            lines.append(("", 0))

        # Header
        lines.append((f"  ● {info.sha}", CP_DLG_SHA))
        if info.parents:
            shas = "  ".join(info.parents.split())
            lines.append((f"  {'Parent(s)':<16}{shas}", CP_DLG_LABEL))

        blank()
        sec("Authorship")
        kv("Author",     info.author)
        kv("Author Date", info.author_date)
        same_person = (info.author.split("<")[0] == info.committer.split("<")[0])
        same_date   = (info.author_date == info.commit_date)
        if not same_person or not same_date:
            kv("Committer",  info.committer)
            kv("Commit Date", info.commit_date)

        sec("Commit Message")
        lines.append(("  " + info.subject, CP_DLG_VALUE))
        if info.body.strip():
            blank()
            for bline in info.body.strip().splitlines():
                lines.append(("  " + bline, CP_DLG_VALUE))

        if info.files:
            sec(f"Changed Files  ({len(info.files)})")
            STATUS_CP = {
                "A": CP_STAT_ADD,
                "M": CP_STAT_MOD,
                "D": CP_STAT_DEL,
            }
            for status, path in info.files:
                cp = STATUS_CP.get(status[0].upper(), CP_DLG_VALUE)
                lines.append((f"  {status:<6}{path}", cp))

        if self.show_diff:
            sec("Diff")
            if not info.diff_loaded:
                lines.append(("  [diff not loaded — press d to fetch]", CP_SCROLL_IND))
            else:
                for dline in info.diff_lines:
                    if dline.startswith("+") and not dline.startswith("+++"):
                        cp = CP_DIFF_ADD
                    elif dline.startswith("-") and not dline.startswith("---"):
                        cp = CP_DIFF_DEL
                    elif dline.startswith("@@"):
                        cp = CP_DIFF_HUNK
                    elif dline.startswith(("diff ", "index ", "--- ", "+++ ")):
                        cp = CP_DIFF_META
                    else:
                        cp = 0
                    lines.append(("  " + dline, cp))
        else:
            blank()
            lines.append(("  [ d — load and toggle diff view ]", CP_SCROLL_IND))

        blank()
        self._lines = lines

    def toggle_diff(self, repo: Optional[str] = None):
        if not self.info.diff_loaded:
            self.info.diff_lines  = load_commit_diff(self.info.sha, repo=repo)
            self.info.diff_loaded = True
        self.show_diff = not self.show_diff
        self._build()

    def scroll(self, delta: int, vis: int):
        max_off = max(0, len(self._lines) - vis)
        self.offset = max(0, min(max_off, self.offset + delta))

    def page(self, direction: int, vis: int):
        self.scroll(direction * max(1, vis - 1), vis)

    def visible(self, vis: int) -> List[Tuple[str, int]]:
        return self._lines[self.offset : self.offset + vis]

    def scroll_pos(self, vis: int) -> str:
        return f"{self.offset + 1}/{len(self._lines)}" if self._lines else ""


# ─── Application ─────────────────────────────────────────────────────────────

class App:

    def __init__(self, stdscr, max_rows: Optional[int], max_cols: Optional[int]):
        self.stdscr   = stdscr
        self.max_rows = max_rows
        self.max_cols = max_cols
        self.repo     = os.getcwd()

        self.active   = PANE_SOURCE
        self.dialog:  Optional[CommitDialog] = None
        self.status   = ""
        self.is_error = False
        self._layout: Optional[Layout] = None
        # Structured status bar: list of (text, cp_id) — cp_id=0 means inherit bar color
        self._status_parts: List[Tuple[str, int]] = []
        self._conflict_str: str = ""   # "" = clean/unknown, else warning text

        self.src_pane = ListPane()
        self.cmp_pane = ListPane()
        self.log_pane = ListPane()

        # Belt-and-suspenders ESC delay (Python 3.9+)
        try:
            curses.set_escdelay(25)
        except AttributeError:
            pass

        self._init_colors()
        self._load_branches()

    # ── Colors ────────────────────────────────────────────────────────────────

    def _init_colors(self):
        curses.start_color()
        curses.use_default_colors()
        has256 = (curses.COLORS >= 256)
        bg = -1   # transparent / default background

        def c(c256: int, c8: int) -> int:
            return c256 if has256 else c8

        pairs = [
            # ID                    foreground                  background
            (CP_HL_FOCUS,      curses.COLOR_BLACK,       c(51,  curses.COLOR_CYAN)),
            (CP_HL_BLUR,       curses.COLOR_BLACK,       c(102, curses.COLOR_WHITE)),
            (CP_BORDER_FOCUS,  c(51,  curses.COLOR_CYAN),   bg),
            (CP_BORDER_BLUR,   c(240, curses.COLOR_WHITE),  bg),
            (CP_STATUS_BAR,    curses.COLOR_BLACK,       c(24,  curses.COLOR_BLUE)),
            (CP_ERROR,         c(196, curses.COLOR_RED),    bg),
            (CP_LOCAL_BRANCH,  c(255, curses.COLOR_WHITE),  bg),
            (CP_REMOTE_BRANCH, c(214, curses.COLOR_YELLOW), bg),
            (CP_CURRENT_BRANCH,c(82,  curses.COLOR_GREEN),  bg),
            (CP_LOCKED_BRANCH, c(118, curses.COLOR_GREEN),  bg),
            (CP_TAG_SRC,       curses.COLOR_BLACK,       c(76,  curses.COLOR_GREEN)),
            (CP_TAG_CMP,       curses.COLOR_BLACK,       c(208, curses.COLOR_YELLOW)),
            (CP_SHA,           c(244, curses.COLOR_WHITE),  bg),
            (CP_PANE_TITLE,    c(51,  curses.COLOR_CYAN),   bg),
            (CP_DLG_SECTION,   c(51,  curses.COLOR_CYAN),   bg),
            (CP_DLG_LABEL,     c(244, curses.COLOR_WHITE),  bg),
            (CP_DLG_VALUE,     c(255, curses.COLOR_WHITE),  bg),
            (CP_DLG_SHA,       c(220, curses.COLOR_YELLOW), bg),
            (CP_DIFF_ADD,      c(82,  curses.COLOR_GREEN),  bg),
            (CP_DIFF_DEL,      c(196, curses.COLOR_RED),    bg),
            (CP_DIFF_HUNK,     c(105, curses.COLOR_CYAN),   bg),
            (CP_DIFF_META,     c(244, curses.COLOR_WHITE),  bg),
            (CP_SCROLL_IND,    c(240, curses.COLOR_WHITE),  bg),
            (CP_STAT_ADD,      c(82,  curses.COLOR_GREEN),  bg),
            (CP_STAT_MOD,      c(214, curses.COLOR_YELLOW), bg),
            (CP_STAT_DEL,      c(196, curses.COLOR_RED),    bg),
            (CP_CONFLICT,      c(196, curses.COLOR_RED),    bg),
            (CP_CLEAN,         c(82,  curses.COLOR_GREEN),  bg),
        ]
        for pid, fg, bg_c in pairs:
            try:
                curses.init_pair(pid, fg, bg_c)
            except curses.error:
                pass   # terminal doesn't support this pair — silently skip

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_branches(self):
        branches, err = load_branches(self.repo)
        if err:
            self._msg(f"Branch load error: {err}", error=True)
            branches = []

        self.src_pane.set_items(branches)
        self.cmp_pane.set_items(list(branches))

        head = current_branch(self.repo)
        for i, b in enumerate(branches):
            if b.short == head:
                self.src_pane.cursor = i
                self.src_pane.locked = b
                break

        n_loc = sum(1 for b in branches if not b.is_remote)
        n_rem = sum(1 for b in branches if b.is_remote)
        self._msg(
            f"Loaded {n_loc} local + {n_rem} remote branches  —  "
            "TAB: cycle panes   ENTER: select   ESC/q: quit"
        )
        self._refresh_log()

    def _refresh_log(self):
        src = self.src_pane.locked
        cmp = self.cmp_pane.locked
        self._conflict_str  = ""
        self._status_parts  = []
        if not src or not cmp:
            self.log_pane.set_items([])
            return
        entries, err = load_log(src.short, cmp.short, self.repo)
        if err:
            self._msg(f"git log error: {err}", error=True)
            self.log_pane.set_items([])
            return

        self.log_pane.set_items(entries)
        n_l = sum(1 for e in entries if e.direction == "left")
        n_r = sum(1 for e in entries if e.direction == "right")

        src_cp = CP_REMOTE_BRANCH if src.is_remote else CP_LOCAL_BRANCH
        cmp_cp = CP_REMOTE_BRANCH if cmp.is_remote else CP_LOCAL_BRANCH

        # "N commits ahead" phrasing: unambiguous direction
        src_label = f" {n_l} commit{'s' if n_l != 1 else ''} ahead of {cmp.short}"
        cmp_label = f" {n_r} commit{'s' if n_r != 1 else ''} ahead of {src.short}"

        self._status_parts = [
            ("◀ ", CP_TAG_SRC),
            (src.short, src_cp),
            (src_label + "   ", 0),
            ("▶ ", CP_TAG_CMP),
            (cmp.short, cmp_cp),
            (cmp_label, 0),
        ]

        # Conflict check (runs git merge-tree, no working tree changes)
        has_conflict, detail = detect_conflicts(src.short, cmp.short, self.repo)
        if has_conflict:
            self._conflict_str = f"  ⚠ merge conflicts: {detail}"
        else:
            self._conflict_str = "  ✓ clean merge"

    def _msg(self, text: str, error: bool = False):
        self.status   = text
        self.is_error = error

    # ── Layout ────────────────────────────────────────────────────────────────

    def _compute_layout(self) -> Layout:
        term_rows, term_cols = self.stdscr.getmaxyx()
        rows = term_rows if self.max_rows is None else min(self.max_rows, term_rows)
        cols = term_cols if self.max_cols is None else min(self.max_cols, term_cols)
        if rows < MIN_ROWS or cols < MIN_COLS:
            raise RuntimeError(
                f"Terminal too small ({term_cols}×{term_rows}).  "
                f"Minimum: {MIN_COLS}w × {MIN_ROWS}h."
            )
        return Layout(rows, cols)

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _put(self, row: int, col: int, text: str, attr: int = 0,
             fill_to: int = 0):
        """Safe addstr. If fill_to > 0, pad/truncate to that width."""
        try:
            if fill_to > 0:
                text = _trunc(text, fill_to).ljust(fill_to)
            self.stdscr.addstr(row, col, text, attr)
        except curses.error:
            pass

    def _box(self, top: int, left: int, h: int, w: int,
             title: str = "", focused: bool = False):
        cp   = CP_BORDER_FOCUS if focused else CP_BORDER_BLUR
        attr = curses.color_pair(cp) | (curses.A_BOLD if focused else 0)

        corners = [
            (top,     left,         curses.ACS_ULCORNER),
            (top,     left + w - 1, curses.ACS_URCORNER),
            (top+h-1, left,         curses.ACS_LLCORNER),
            (top+h-1, left + w - 1, curses.ACS_LRCORNER),
        ]
        for r, c, ch in corners:
            try:
                self.stdscr.addch(r, c, ch, attr)
            except curses.error:
                pass

        for c in range(left + 1, left + w - 1):
            try:
                self.stdscr.addch(top,     c, curses.ACS_HLINE, attr)
                self.stdscr.addch(top+h-1, c, curses.ACS_HLINE, attr)
            except curses.error:
                pass

        for r in range(top + 1, top + h - 1):
            try:
                self.stdscr.addch(r, left,         curses.ACS_VLINE, attr)
                self.stdscr.addch(r, left + w - 1, curses.ACS_VLINE, attr)
            except curses.error:
                pass

        if title:
            title_attr = curses.color_pair(CP_PANE_TITLE) | curses.A_BOLD
            text = f" {title} "
            for i, ch in enumerate(text):
                if left + 2 + i >= left + w - 1:
                    break
                try:
                    self.stdscr.addch(top, left + 2 + i, ch, title_attr)
                except curses.error:
                    pass

    def _scroll_badge(self, top: int, left: int, h: int, w: int, text: str):
        if not text:
            return
        col = left + w - len(text) - 2
        if col > left + 1:
            self._put(top + h - 1, col, text, curses.color_pair(CP_SCROLL_IND))

    # ── Branch pane ───────────────────────────────────────────────────────────

    def _draw_branch_pane(self, pane: ListPane, rect: tuple, title: str,
                          vis: int, focused: bool):
        top, left, h, w = rect
        iw = w - 2
        self._box(top, left, h, w, title, focused)

        for i, item in enumerate(pane.visible(vis)):
            abs_i      = pane.offset + i
            is_cursor  = (abs_i == pane.cursor)
            is_locked  = (item is pane.locked)

            if is_locked:
                base   = curses.color_pair(CP_LOCKED_BRANCH) | curses.A_BOLD
                prefix = "● "
            elif item.is_current:
                base   = curses.color_pair(CP_CURRENT_BRANCH) | curses.A_BOLD
                prefix = "* "
            elif item.is_remote:
                base   = curses.color_pair(CP_REMOTE_BRANCH)
                prefix = "  "
            else:
                base   = curses.color_pair(CP_LOCAL_BRANCH)
                prefix = "  "

            if is_cursor and focused:
                attr = curses.color_pair(CP_HL_FOCUS) | curses.A_BOLD
            else:
                attr = base

            self._put(top + 1 + i, left + 1, prefix + item.short, attr, fill_to=iw)

        self._scroll_badge(top, left, h, w, pane.scroll_pos())

    # ── Log pane ──────────────────────────────────────────────────────────────

    def _draw_log_pane(self, ly: Layout, focused: bool):
        top, left, h, w = ly.log
        vis   = ly.log_ih
        pane  = self.log_pane

        src = self.src_pane.locked.short if self.src_pane.locked else "none"
        cmp = self.cmp_pane.locked.short if self.cmp_pane.locked else "none"
        self._box(top, left, h, w, f"LOG  ◀ {src}  │  ▶ {cmp}", focused)

        tag_w = ly.log_tag_w
        sha_w = ly.log_sha_w
        msg_w = ly.log_msg_w

        for i, entry in enumerate(pane.visible(vis)):
            abs_i    = pane.offset + i
            is_cur   = (abs_i == pane.cursor)
            r        = top + 1 + i
            c        = left + 1
            is_left  = (entry.direction == "left")

            arrow    = "◀" if is_left else "▶"
            tag_name = src if is_left else cmp
            tag_cp   = CP_TAG_SRC if is_left else CP_TAG_CMP
            tag_text = _trunc(f"{arrow} {tag_name}", tag_w).ljust(tag_w)
            sha_text = _trunc(entry.sha, sha_w).ljust(sha_w)
            msg_text = _trunc(entry.message, msg_w).ljust(msg_w)

            if is_cur and focused:
                full = (tag_text + " " + sha_text + " " + msg_text).ljust(ly.log_iw)
                self._put(r, c, full, curses.color_pair(CP_HL_FOCUS) | curses.A_BOLD)
            else:
                self._put(r, c,              tag_text, curses.color_pair(tag_cp) | curses.A_BOLD)
                self._put(r, c + tag_w + 1,  sha_text, curses.color_pair(CP_SHA))
                self._put(r, c + tag_w + sha_w + 2, msg_text, 0)

        self._scroll_badge(top, left, h, w, pane.scroll_pos())

    # ── Status bar ────────────────────────────────────────────────────────────

    def _draw_status(self, ly: Layout):
        row, col, _, width = ly.status
        pane_name = ["SOURCE", "COMPARE-TO", "LOG"][self.active]
        right_tag = f" FOCUS:{pane_name} "
        bar_attr  = curses.color_pair(CP_STATUS_BAR)

        if self.is_error:
            # Plain error — single color, no segments
            full = _trunc(self.status, width - len(right_tag) - 1)
            full = (full.ljust(width - len(right_tag)) + right_tag)[:width]
            try:
                self.stdscr.addstr(row, col, full,
                                   curses.color_pair(CP_ERROR) | curses.A_BOLD)
            except curses.error:
                pass
            return

        # Fill entire bar with background first
        try:
            self.stdscr.addstr(row, col, " " * width, bar_attr)
        except curses.error:
            pass

        # Right-side focus tag
        try:
            self.stdscr.addstr(row, col + width - len(right_tag),
                               right_tag, bar_attr | curses.A_BOLD)
        except curses.error:
            pass

        avail = width - len(right_tag) - 1   # usable columns for left content

        if self._status_parts:
            # Render structured segments: branch names in their own colors
            parts = list(self._status_parts)
            # Append conflict indicator
            if self._conflict_str:
                is_conflict = self._conflict_str.lstrip().startswith("⚠")
                parts.append((self._conflict_str,
                               CP_CONFLICT if is_conflict else CP_CLEAN))

            x = col
            for text, cp in parts:
                if x - col >= avail:
                    break
                remaining = avail - (x - col)
                chunk = _trunc(text, remaining)
                attr = (curses.color_pair(cp) | curses.A_BOLD) if cp else bar_attr
                try:
                    self.stdscr.addstr(row, x, chunk, attr)
                except curses.error:
                    pass
                x += len(chunk)
        else:
            # Fallback: plain text status
            text = _trunc(self.status, avail)
            try:
                self.stdscr.addstr(row, col, text, bar_attr)
            except curses.error:
                pass

    # ── Commit dialog ─────────────────────────────────────────────────────────

    def _draw_dialog(self, ly: Layout):
        dlg   = self.dialog
        rows  = ly.rows
        cols  = ly.cols

        # Pad from screen edges
        pad_y, pad_x = 2, 3
        dlg_h  = rows - pad_y * 2
        dlg_w  = cols - pad_x * 2
        top    = pad_y
        left   = pad_x
        inner_h = dlg_h - 2
        inner_w = dlg_w - 2

        # Fill background before drawing (masks content beneath)
        blank = " " * dlg_w
        for r in range(top, top + dlg_h):
            self._put(r, left, blank)

        sha_short = dlg.info.sha[:12] + "…" if len(dlg.info.sha) > 12 else dlg.info.sha
        self._box(top, left, dlg_h, dlg_w,
                  f"COMMIT DETAILS  {sha_short}", focused=True)

        for i, (text, cp) in enumerate(dlg.visible(inner_h)):
            if i >= inner_h:
                break
            r = top + 1 + i
            c = left + 1

            # Split label/value lines for two-tone rendering
            if cp == CP_DLG_LABEL and len(text) > 18:
                label_part = text[:18]
                value_part = text[18:]
                self._put(r, c,      _trunc(label_part, 18).ljust(18),
                          curses.color_pair(CP_DLG_LABEL))
                self._put(r, c + 18, value_part,
                          curses.color_pair(CP_DLG_VALUE), fill_to=inner_w - 18)
            elif cp == CP_DLG_SHA:
                self._put(r, c, _trunc(text, inner_w).ljust(inner_w),
                          curses.color_pair(CP_DLG_SHA) | curses.A_BOLD)
            else:
                attr = curses.color_pair(cp) if cp else 0
                self._put(r, c, _trunc(text, inner_w).ljust(inner_w), attr)

        # Hint + scroll indicator in bottom border
        ind       = dlg.scroll_pos(inner_h)
        hint      = " ↑↓:scroll  PgUp/PgDn:page  Home/End  d:diff  q/ESC:close "
        hint_text = _trunc(hint, dlg_w - len(ind) - 2).ljust(dlg_w - len(ind) - 2)
        full_hint = (hint_text + " " + ind + " ")[:dlg_w]
        try:
            self.stdscr.addstr(top + dlg_h - 1, left, full_hint,
                               curses.color_pair(CP_STATUS_BAR))
        except curses.error:
            pass

    # ── Full redraw ───────────────────────────────────────────────────────────

    def _redraw(self):
        self.stdscr.erase()
        try:
            ly          = self._compute_layout()
            self._layout = ly
        except RuntimeError as exc:
            self._put(0, 0, str(exc),
                      curses.color_pair(CP_ERROR) | curses.A_BOLD)
            self.stdscr.refresh()
            return

        self._draw_branch_pane(
            self.src_pane, ly.source, "SOURCE BRANCH",
            ly.src_ih, self.active == PANE_SOURCE)
        self._draw_branch_pane(
            self.cmp_pane, ly.compare, "COMPARE-TO BRANCH",
            ly.cmp_ih, self.active == PANE_COMPARE)
        self._draw_log_pane(ly, self.active == PANE_LOG)
        self._draw_status(ly)

        if self.dialog:
            self._draw_dialog(ly)

        self.stdscr.refresh()

    # ── Input handling ────────────────────────────────────────────────────────

    def _key_dialog(self, key: int):
        dlg = self.dialog
        ly  = self._layout
        vis = (ly.rows - 6) if ly else 20

        if key in (27, ord('q')):
            self.dialog = None
            self._msg("Returned to log.")
        elif key in (curses.KEY_UP,    ord('k')):
            dlg.scroll(-1, vis)
        elif key in (curses.KEY_DOWN,  ord('j')):
            dlg.scroll(1, vis)
        elif key == curses.KEY_PPAGE:
            dlg.page(-1, vis)
        elif key == curses.KEY_NPAGE:
            dlg.page(1, vis)
        elif key == curses.KEY_HOME:
            dlg.offset = 0
        elif key == curses.KEY_END:
            dlg.offset = max(0, len(dlg._lines) - vis)
        elif key == ord('d'):
            self._msg("Loading diff…")
            self._redraw()
            dlg.toggle_diff(repo=self.repo)

    def _key_main(self, key: int) -> bool:
        """Return False to quit."""

        if key == ord('\t'):
            self.active   = (self.active + 1) % 3
            self.is_error = False
            return True

        if key in (27, ord('q')):
            return False

        ly   = self._layout
        pane = [self.src_pane, self.cmp_pane, self.log_pane][self.active]
        vis  = ([ly.src_ih, ly.cmp_ih, ly.log_ih][self.active]) if ly else 10

        if key in (curses.KEY_UP,    ord('k')):
            pane.move(-1, vis);  self.is_error = False
        elif key in (curses.KEY_DOWN, ord('j')):
            pane.move(1, vis);   self.is_error = False
        elif key == curses.KEY_PPAGE:
            pane.page(-1, vis)
        elif key == curses.KEY_NPAGE:
            pane.page(1, vis)
        elif key == curses.KEY_HOME:
            pane.jump_home()
        elif key == curses.KEY_END:
            pane.jump_end(vis)
        elif key in (ord('\n'), curses.KEY_ENTER, ord(' ')):
            self._handle_enter()

        return True

    def _handle_enter(self):
        if self.active == PANE_SOURCE:
            item = self.src_pane.current()
            if item:
                self.src_pane.locked = item
                self._conflict_str  = ""
                self._status_parts  = []
                self._msg(f"Source locked → {item.short}  (checking merge…)")
                self._refresh_log()

        elif self.active == PANE_COMPARE:
            item = self.cmp_pane.current()
            if item:
                self.cmp_pane.locked = item
                self._conflict_str  = ""
                self._status_parts  = []
                self._msg(f"Compare-to locked → {item.short}  (checking merge…)")
                self._refresh_log()

        elif self.active == PANE_LOG:
            entry = self.log_pane.current()
            if entry:
                self._msg(f"Loading commit {entry.sha}…")
                self._redraw()
                info = load_commit_info(entry.sha, repo=self.repo)
                if info.error:
                    self._msg(f"Error: {info.error}", error=True)
                else:
                    self.dialog = CommitDialog(info)
                    self._msg(f"Commit {entry.sha} — q/ESC: close   d: diff")

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        curses.curs_set(0)
        self.stdscr.keypad(True)
        self.stdscr.timeout(100)

        def _sigwinch(sig, frame):
            curses.endwin()
            self.stdscr.refresh()

        signal.signal(signal.SIGWINCH, _sigwinch)

        while True:
            try:
                self._redraw()
                key = self.stdscr.getch()
                if key == curses.ERR:
                    continue

                if self.dialog:
                    self._key_dialog(key)
                else:
                    if not self._key_main(key):
                        break

            except KeyboardInterrupt:
                break
            except curses.error:
                pass   # Ignore transient resize races


# ─── Utilities ────────────────────────────────────────────────────────────────

def _trunc(text: str, width: int) -> str:
    """Truncate string to at most `width` chars, appending '…' if cut."""
    if width <= 0:
        return ""
    return text if len(text) <= width else text[:width - 1] + "…"


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    max_rows: Optional[int] = None
    max_cols: Optional[int] = None

    try:
        opts, _ = getopt.getopt(sys.argv[1:], "h", ["rows=", "cols=", "help"])
    except getopt.GetoptError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(__doc__)
        sys.exit(1)

    for opt, val in opts:
        if opt in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
        elif opt == "--rows":
            try:
                max_rows = int(val)
            except ValueError:
                print(f"--rows must be an integer, got: {val!r}", file=sys.stderr)
                sys.exit(1)
        elif opt == "--cols":
            try:
                max_cols = int(val)
            except ValueError:
                print(f"--cols must be an integer, got: {val!r}", file=sys.stderr)
                sys.exit(1)

    # Confirm CWD is a git repo
    _, err, rc = _git("rev-parse", "--git-dir")
    if rc != 0:
        print(f"Not a git repository: {os.getcwd()}", file=sys.stderr)
        sys.exit(1)

    # Restore terminal before any unhandled traceback
    _orig_hook = sys.excepthook
    def _safe_hook(etype, value, tb):
        try:
            curses.endwin()
        except Exception:
            pass
        _orig_hook(etype, value, tb)
    sys.excepthook = _safe_hook

    def _run(stdscr):
        App(stdscr, max_rows, max_cols).run()

    try:
        curses.wrapper(_run)
    except RuntimeError as exc:
        print(f"Fatal: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()