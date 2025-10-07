#!/usr/bin/env python3

import os
import sys
import subprocess
import termios
import tty
import contextlib
from typing import List, Tuple, Dict

# ANSI color codes
COLORS = {
    'lightgreen': '\033[1;32m',
    'whiteonblue': '\033[1;37;44m',
    'yellowonpurple': '\033[1;93;45m',
    'whiteoncyan': '\033[1;37;46m',
    'lightblue': '\033[1;34m',
    'lightpurple': '\033[38;5;177m',
    'silver': '\033[90m',
    'cyan': '\033[96m',
    'darkblue': '\033[34m',
    'darkgray': '\033[90m',
    'green': '\033[0;32m',
    'yellow': '\033[93m',
    'red': '\033[91m',
    'orange': '\033[38;5;208m',
    'reset': '\033[0m',
    'bg_blue': '\033[44m',
    'white': '\033[97m',
    'black': '\033[30m',
    'clear_line': '\r\033[K',
    'move_up': '\033[A',
    'save_cursor': '\033[s',
    'restore_cursor': '\033[u',
    'clear_screen': '\033[2J\033[H'
}

# Maximum number of items to display in the scrollable window
MAX_ITEMS = 8

def log(message: str):
    """Log an info message with cyan color."""
    print(f"{COLORS['cyan']}Info: {COLORS['silver']}{message}{COLORS['reset']}")

def log_ok(message: str):
    """Log a success message with green color."""
    print(f"{COLORS['green']}OK: {COLORS['lightgreen']}{message}{COLORS['reset']}")

def warning(message: str):
    """Log a warning message with yellow color."""
    print(f"{COLORS['yellow']}Warning: {message}{COLORS['reset']}")

def error(message: str, exit_code: int = 1):
    """Log an error message with red color and exit."""
    print(f"{COLORS['red']}Error: {message}{COLORS['reset']}")
    exit(exit_code)

@contextlib.contextmanager
def raw_mode():
    """Context manager for raw terminal input mode."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def read_key():
    """Read a keypress and return the key."""
    with raw_mode():
        key = sys.stdin.read(1)
        
        # Handle escape sequences for arrow keys
        if key == '\x1b':  # Escape character
            sys.stdin.read(1)  # Read the '['
            next_key = sys.stdin.read(1)
            if next_key == 'A':
                return 'UP'
            elif next_key == 'B':
                return 'DOWN'
            elif next_key == 'C':
                return 'RIGHT'
            elif next_key == 'D':
                return 'LEFT'
            return 'ESC'
        return key

def check_git_repo():
    """Check if the current directory is a git repository."""
    if not os.path.isdir('.git'):
        try:
            result = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], 
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode != 0 or result.stdout.strip() != 'true':
                error("Not a git repository. Please run this script inside a git repository.")
        except FileNotFoundError:
            error("Git command not found. Please install git and try again.")
    return True

def get_branches() -> Tuple[List[str], str]:
    """Get all branches and the current branch."""
    try:
        result = subprocess.run(['git', 'branch'], 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            error(f"Failed to get branches: {result.stderr}")
        
        current_branch = None
        branches = []
        
        for line in result.stdout.splitlines():
            branch = line.strip()
            if branch.startswith('* '):
                current_branch = branch[2:]  # Remove the '* ' prefix
                branches.append(branch[2:])
            else:
                branches.append(branch)
        
        return branches, current_branch
    except Exception as e:
        error(f"Error getting branches: {str(e)}")

def get_remote_branches() -> List[str]:
    """Get all remote branches from origin."""
    try:
        # First, fetch the latest remote information
        subprocess.run(['git', 'fetch', '--quiet'], 
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # Get remote branches
        result = subprocess.run(['git', 'ls-remote', '--heads', 'origin'], 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            warning(f"Failed to get remote branches: {result.stderr}")
            return []
        
        remote_branches = []
        for line in result.stdout.splitlines():
            if line.strip():
                # Format: "commit_hash refs/heads/branch_name"
                parts = line.split('\t')
                if len(parts) >= 2 and parts[1].startswith('refs/heads/'):
                    branch_name = parts[1].replace('refs/heads/', '')
                    remote_branches.append(branch_name)
        
        return remote_branches
    except Exception as e:
        warning(f"Error getting remote branches: {str(e)}")
        return []

def get_all_branches() -> Tuple[List[Dict], str]:
    """Get all local and remote branches with their metadata."""
    local_branches, current_branch = get_branches()
    remote_branches = get_remote_branches()
    
    all_branches = []
    
    # Add local branches
    for branch in local_branches:
        all_branches.append({
            'name': branch,
            'type': 'local',
            'display_name': branch,
            'is_current': branch == current_branch
        })
    
    # Add remote branches that don't exist locally
    for remote_branch in remote_branches:
        if remote_branch not in local_branches:
            all_branches.append({
                'name': remote_branch,
                'type': 'remote',
                'display_name': f"origin/{remote_branch}",
                'is_current': False
            })
    
    return all_branches, current_branch

def get_last_commit(branch: str, is_remote: bool = False) -> str:
    """Get the last commit message (first line only) for a branch."""
    try:
        branch_ref = f"origin/{branch}" if is_remote else branch
        result = subprocess.run(['git', 'log', '-1', '--pretty=%s', branch_ref], 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            return "No commits yet" if not is_remote else "Unable to fetch"
        
        message = result.stdout.strip()
        # Limit message length for display purposes
        if len(message) > 50:
            message = message[:47] + "..."
        return message
    except Exception as e:
        return f"Error getting commit: {str(e)}"

def switch_to_branch(branch_name: str):
    """Switch to the specified branch."""
    try:
        result = subprocess.run(['git', 'checkout', branch_name], 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            error(f"Failed to switch to branch {branch_name}: {result.stderr}")
        log_ok(f"Switched to branch '{branch_name}'")
    except Exception as e:
        error(f"Error switching branches: {str(e)}")

def checkout_remote_branch(branch_name: str):
    """Checkout a remote branch and create a local tracking branch."""
    try:
        # Create and checkout a new local branch that tracks the remote branch
        result = subprocess.run(['git', 'checkout', '-b', branch_name, f'origin/{branch_name}'], 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            error(f"Failed to checkout remote branch {branch_name}: {result.stderr}")
        log_ok(f"Created local branch '{branch_name}' tracking 'origin/{branch_name}' and switched to it")
    except Exception as e:
        error(f"Error checking out remote branch: {str(e)}")

def create_branch(branch_name: str):
    """Create a new branch and switch to it."""
    try:
        result = subprocess.run(['git', 'checkout', '-b', branch_name], 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            error(f"Failed to create branch {branch_name}: {result.stderr}")
        log_ok(f"Created and switched to branch '{branch_name}'")
    except Exception as e:
        error(f"Error creating branch: {str(e)}")

def delete_branch(branch_name: str):
    """Delete the specified branch."""
    try:
        result = subprocess.run(['git', 'branch', '-d', branch_name], 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            warning(f"Failed to delete branch {branch_name} with -d (safe delete). Trying force delete...")
            force_result = subprocess.run(['git', 'branch', '-D', branch_name], 
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if force_result.returncode != 0:
                error(f"Failed to force delete branch {branch_name}: {force_result.stderr}")
            else:
                log_ok(f"Force deleted branch '{branch_name}'")
        else:
            log_ok(f"Deleted branch '{branch_name}'")
    except Exception as e:
        error(f"Error deleting branch: {str(e)}")

def clear_screen():
    """Clear the screen."""
    print(COLORS['clear_screen'], end='')

def print_scrollable_menu(branches: List[Dict], current_branch: str, top_index: int, selected_index: int, commit_messages: Dict[str, str], branch_display_width: int, current_directory: str):   
    """Print the scrollable branch selection menu."""
    
    # Calculate the end index for display (limited by MAX_ITEMS and list length)
    end_index = min(top_index + MAX_ITEMS, len(branches))
    
    # Unicode characters for indicators
    current_indicator = "⭐"
    remote_indicator = "🌐"
    
    # Clear screen before redrawing
    print(COLORS['clear_screen'], end='')
    
    # Print the header
    print("\n" + "="*80)
    print(f"BRANCHMAN - Current branch: {COLORS['lightgreen']}{current_branch}{COLORS['reset']} on project {COLORS['whiteoncyan']}{current_directory}{COLORS['reset']}")
    print("="*80)
    
    # Always show top scroll indicator but change color based on status
    up_color = COLORS['lightpurple'] if top_index > 0 else COLORS['silver']
    print(f"   {up_color}↑ more branches above ↑{COLORS['reset']}")
    
    # Print visible branches
    for i in range(top_index, end_index):
        branch_info = branches[i]
        branch_name = branch_info['name']
        display_name = branch_info['display_name']
        is_current = branch_info['is_current']
        is_remote = branch_info['type'] == 'remote'
        
        # Choose appropriate indicator
        if is_current:
            indicator = current_indicator
        elif is_remote:
            indicator = remote_indicator
        else:
            indicator = "  "
        
        # Pad the display name to ensure consistent width
        padded_branch = display_name.ljust(branch_display_width)
        
        # Get commit message for this branch
        commit_key = f"{branch_name}_{branch_info['type']}"
        commit_msg = commit_messages.get(commit_key, "")
        
        # Color coding for different branch types
        if is_remote:
            branch_color = COLORS['orange']
        else:
            branch_color = COLORS['darkblue']
        
        # Highlight the selected branch with blue background and white text
        if i == selected_index:
            print(f"{i+1:2d}. {indicator} {COLORS['bg_blue']}{COLORS['white']}{padded_branch}{COLORS['reset']} - {COLORS['cyan']}{commit_msg}{COLORS['reset']}")
        else:
            print(f"{i+1:2d}. {indicator} {branch_color}{padded_branch}{COLORS['reset']} - {COLORS['darkgray']}{commit_msg}{COLORS['reset']}")
    
    # Always show bottom scroll indicator but change color based on status
    down_color = COLORS['lightpurple'] if end_index < len(branches) else COLORS['silver']
    print(f"   {down_color}↓ more branches below ↓{COLORS['reset']}")
    
    # Print the footer
    print("\n" + "-"*80)
    print(f"Navigation: {COLORS['cyan']}↑/↓{COLORS['reset']} - Move selection   {COLORS['green']}[ENTER]{COLORS['reset']} - Switch/Checkout branch")
    print(f"Options:      {COLORS['cyan']}N{COLORS['reset']} - New branch             {COLORS['yellow']}D{COLORS['reset']} - Delete branch")
    print(f"              {COLORS['green']}R{COLORS['reset']} - Branch with suffix     {COLORS['red']}Q{COLORS['reset']} - Quit")
    print(f"Legend:     {current_indicator} Current   {remote_indicator} Remote")
    print("-"*80)
    print(f"Enter your choice: ", end='', flush=True)

def handle_scrolling(key: str, branches: List[Dict], selected_index: int, top_index: int) -> Tuple[int, int]:
    """Handle arrow key navigation and scrolling."""
    new_selected_index = selected_index
    new_top_index = top_index
    
    if key == 'UP':
        if selected_index > 0:
            new_selected_index = selected_index - 1
            # Scroll up if selection moves out of view
            if new_selected_index < top_index:
                new_top_index = top_index - 1
    elif key == 'DOWN':
        if selected_index < len(branches) - 1:
            new_selected_index = selected_index + 1
            # Scroll down if selection moves out of view
            if new_selected_index >= top_index + MAX_ITEMS:
                new_top_index = top_index + 1
    
    return new_selected_index, new_top_index

def main():
    """Main function."""
    check_git_repo()
    branches, current_branch = get_all_branches()
    
    # get the name of the current directory
    current_directory = os.path.basename(os.getcwd())   
    
    # Initialize indices for scrolling
    current_index = 0
    for i, branch in enumerate(branches):
        if branch['is_current']:
            current_index = i
            break
    
    selected_index = current_index
    top_index = max(0, min(selected_index, len(branches) - MAX_ITEMS))
    
    # Find the longest branch display name to ensure consistent display width
    max_branch_length = max(len(branch['display_name']) for branch in branches) if branches else 0
    branch_display_width = max(25, max_branch_length)  # At least 25 chars wide
    
    # Get commit messages once to avoid repeated git commands
    commit_messages = {}
    for branch in branches:
        is_remote = branch['type'] == 'remote'
        commit_key = f"{branch['name']}_{branch['type']}"
        commit_messages[commit_key] = get_last_commit(branch['name'], is_remote)
    
    clear_screen()
    
    while True:
        # Print the menu
        print_scrollable_menu(branches, current_branch, top_index, selected_index, commit_messages, branch_display_width, current_directory)
        
        # Get user input
        key = read_key()
        
        if key in ('UP', 'DOWN'):
            selected_index, top_index = handle_scrolling(key, branches, selected_index, top_index)
        elif key in ('\r', '\n'):  # Enter key
            selected_branch = branches[selected_index]
            branch_name = selected_branch['name']
            is_remote = selected_branch['type'] == 'remote'
            
            if selected_branch['is_current']:
                clear_screen()
                log(f"Already on branch '{current_branch}'")
            elif is_remote:
                clear_screen()
                checkout_remote_branch(branch_name)
                branches, current_branch = get_all_branches()
                # Find new current branch index
                for i, branch in enumerate(branches):
                    if branch['is_current']:
                        selected_index = i
                        break
                top_index = max(0, min(selected_index, len(branches) - MAX_ITEMS))
                # Update commit messages
                for branch in branches:
                    is_remote_branch = branch['type'] == 'remote'
                    commit_key = f"{branch['name']}_{branch['type']}"
                    commit_messages[commit_key] = get_last_commit(branch['name'], is_remote_branch)
            else:
                clear_screen()
                switch_to_branch(branch_name)
                branches, current_branch = get_all_branches()
                # Find new current branch index
                for i, branch in enumerate(branches):
                    if branch['is_current']:
                        selected_index = i
                        break
                top_index = max(0, min(selected_index, len(branches) - MAX_ITEMS))
                # Update commit messages
                for branch in branches:
                    is_remote_branch = branch['type'] == 'remote'
                    commit_key = f"{branch['name']}_{branch['type']}"
                    commit_messages[commit_key] = get_last_commit(branch['name'], is_remote_branch)
        elif key.upper() == 'Q':
            clear_screen()
            log("Exiting...")
            break
        elif key.upper() == 'N':
            clear_screen()
            new_branch = input("Enter new branch name (leave empty to cancel): ").strip()
            if new_branch:
                create_branch(new_branch)
                branches, current_branch = get_all_branches()
                # Find new current branch index
                for i, branch in enumerate(branches):
                    if branch['is_current']:
                        selected_index = i
                        break
                top_index = max(0, min(selected_index, len(branches) - MAX_ITEMS))
                # Update commit messages
                for branch in branches:
                    is_remote_branch = branch['type'] == 'remote'
                    commit_key = f"{branch['name']}_{branch['type']}"
                    commit_messages[commit_key] = get_last_commit(branch['name'], is_remote_branch)
            else:
                warning("Branch name cannot be empty")
        elif key.upper() == 'D':
            clear_screen()
            selected_branch = branches[selected_index]
            branch_to_delete = selected_branch['name']
            is_remote = selected_branch['type'] == 'remote'
            
            if is_remote:
                warning("Cannot delete remote branches from this interface.")
            elif selected_branch['is_current']:
                warning("Cannot delete the current branch. Switch to another branch first.")
            else:
                confirm = input(f"Delete branch '{branch_to_delete}'? (y/N): ").strip().lower()
                if confirm == 'y':
                    delete_branch(branch_to_delete)
                    branches, current_branch = get_all_branches()
                    selected_index = min(selected_index, len(branches) - 1)
                    top_index = max(0, min(selected_index, len(branches) - MAX_ITEMS))
                    # Update commit messages
                    for branch in branches:
                        is_remote_branch = branch['type'] == 'remote'
                        commit_key = f"{branch['name']}_{branch['type']}"
                        commit_messages[commit_key] = get_last_commit(branch['name'], is_remote_branch)
        elif key.upper() == 'R':
            clear_screen()
            suffix = input(f"Enter suffix to append to '{current_branch}': ").strip()
            if suffix:
                new_branch_name = f"{current_branch}.{suffix}"
                create_branch(new_branch_name)
                branches, current_branch = get_all_branches()
                # Find new current branch index
                for i, branch in enumerate(branches):
                    if branch['is_current']:
                        selected_index = i
                        break
                top_index = max(0, min(selected_index, len(branches) - MAX_ITEMS))
                # Update commit messages
                for branch in branches:
                    is_remote_branch = branch['type'] == 'remote'
                    commit_key = f"{branch['name']}_{branch['type']}"
                    commit_messages[commit_key] = get_last_commit(branch['name'], is_remote_branch)
            else:
                warning("Suffix cannot be empty")
        
        # Clear input line before redrawing menu
        print(COLORS['clear_line'], end='')

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
