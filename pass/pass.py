#!/usr/bin/env python3
#
# pass.py - Interactive GPG + pass(1) Password Manager
#
# Guided CLI wrapper around GnuPG and the standard Unix password manager
# (pass). Walks the user through selecting or creating a GPG key, then
# storing a password in the pass password store.
#
# Workflow:
#   1. Checks that gpg and pass are installed.
#   2. Lists existing GPG secret keys and lets the user pick one,
#      or generates a new 4096-bit RSA key pair if none exist.
#   3. Initializes ~/.password-store with the chosen key if needed.
#   4. Prompts for a password name and value, confirms, and stores it
#      via `pass insert`.
#
# Requirements:
#   - gnupg (gpg)
#   - pass  (https://www.passwordstore.org)
#
# Usage:
#   python3 pass.py
#
import subprocess
import sys
import os
import getpass
import tempfile
from datetime import datetime

# Color definitions
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    PURPLE = '\033[0;35m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # No Color

# Emoji definitions
class Emojis:
    KEY = "🔑"
    LOCK = "🔒"
    SUCCESS = "✅"
    ERROR = "❌"
    WARNING = "⚠️ "  # needs extra padding for better alignment
    INFO = "ℹ️ "     # needs extra padding for better alignment
    FOLDER = "📁"
    ADD = "➕"
    REFRESH = "🔄"

def print_color(emoji, text):
    """Print colored text with emoji"""
    print(f"{emoji} {text}")

def wait_for_enter():
    """Wait for user to press Enter"""
    input(f"{Emojis.INFO} {Colors.CYAN}Press [Enter] to continue...{Colors.NC}")

def run_command(command, capture_output=True, shell=False):
    """Run a shell command and return the result"""
    try:
        if shell:
            result = subprocess.run(command, shell=True, capture_output=capture_output, 
                                  text=True, check=False)
        else:
            result = subprocess.run(command, capture_output=capture_output, 
                                  text=True, check=False)
        return result
    except Exception as e:
        print_color(Emojis.ERROR, f"{Colors.RED}Error running command: {e}{Colors.NC}")
        return None

def check_command_exists(command):
    """Check if a command exists in the system"""
    result = run_command(['which', command])
    return result and result.returncode == 0

def get_gpg_keys():
    """Get list of GPG secret keys with detailed information"""
    result = run_command(['gpg', '--list-secret-keys', '--with-colons'])
    if not result or result.returncode != 0:
        return []

    keys = []
    lines = result.stdout.strip().split('\n')
    current_key = None
    
    for line in lines:
        if not line:
            continue
            
        parts = line.split(':')
        
        if line.startswith('sec:'):
            # Secret key line: sec:trust:key_length:algo:key_id:creation_date:...
            if len(parts) >= 6:
                current_key = {
                    'id': parts[4][-16:] if len(parts[4]) > 16 else parts[4],  # Last 16 chars for display
                    'full_id': parts[4],
                    'algo': parts[3],
                    'length': parts[2],
                    'created': parts[5],
                    'name': '',
                    'email': ''
                }
                keys.append(current_key)
        
        elif line.startswith('uid:') and current_key:
            # User ID line: uid:trust:::::::::name <email>:...
            if len(parts) >= 10 and parts[9]:
                uid_info = parts[9]
                # Parse "Name <email>" format
                if '<' in uid_info and '>' in uid_info:
                    name_part = uid_info.split('<')[0].strip()
                    email_part = uid_info.split('<')[1].split('>')[0].strip()
                    current_key['name'] = name_part
                    current_key['email'] = email_part
                else:
                    current_key['name'] = uid_info
    
    return keys

def format_timestamp(timestamp_str):
    """Convert Unix timestamp to readable date"""
    try:
        if timestamp_str and timestamp_str.isdigit():
            dt = datetime.fromtimestamp(int(timestamp_str))
            return dt.strftime('%Y-%m-%d')
        return timestamp_str
    except:
        return timestamp_str

def check_gpg_key():
    """Check for existing GPG keys"""
    print_color(Emojis.INFO, f"{Colors.CYAN}Checking for existing GPG keys...{Colors.NC}")
    
    keys = get_gpg_keys()
    
    if keys:
        print_color(Emojis.SUCCESS, f"{Colors.GREEN}GPG key(s) found!{Colors.NC}")
        return select_gpg_key(keys)
    else:
        print_color(Emojis.WARNING, f"{Colors.YELLOW}No GPG key found. A GPG key is required to encrypt passwords in the password store.{Colors.NC}")
        print_color(Emojis.INFO, f"{Colors.CYAN}Let's create one now.{Colors.NC}")
        return create_gpg_key()

def select_gpg_key(keys):
    """Select an existing GPG key"""
    print()
    print_color(Emojis.KEY, f"{Colors.PURPLE}Available GPG keys:{Colors.NC}")
    print()
    
    for i, key in enumerate(keys, 1):
        algo_display = f"{key['algo']}{key['length']}" if key['algo'] and key['length'] else "Unknown"
        created_display = format_timestamp(key['created'])
        name_email = f"{key['name']} <{key['email']}>" if key['name'] or key['email'] else "No name/email"
        
        key_info = f"{Colors.CYAN}[{i}] {Colors.PURPLE}{key['id']}{Colors.CYAN} ({algo_display}) - {name_email} (created: {created_display}){Colors.NC}"
        print_color(Emojis.KEY, key_info)
    
    print()
    try:
        key_num = input(f"{Emojis.KEY} {Colors.PURPLE}Enter the number of the key to use: {Colors.NC}")
        key_num = int(key_num)
        
        if key_num < 1 or key_num > len(keys):
            raise ValueError("Invalid selection")
        
        selected_key = keys[key_num - 1]
        gpg_key_id = selected_key['full_id']
        
        print_color(Emojis.SUCCESS, f"{Colors.GREEN}Selected GPG key: {selected_key['id']}{Colors.NC}")
        return prompt_for_key_name(gpg_key_id)
        
    except ValueError:
        print_color(Emojis.ERROR, f"{Colors.RED}Invalid selection!{Colors.NC}")
        return select_gpg_key(keys)
    except KeyboardInterrupt:
        raise  # Re-raise to let main() handle it

def create_gpg_key():
    """Create a new GPG key"""
    print()
    try:
        gpg_name = input(f"{Emojis.ADD} {Colors.PURPLE}Enter your name for the GPG key: {Colors.NC}")
        gpg_email = input(f"{Emojis.ADD} {Colors.PURPLE}Enter your email for the GPG key: {Colors.NC}")
        
        if not gpg_name.strip() or not gpg_email.strip():
            print_color(Emojis.ERROR, f"{Colors.RED}Name and email cannot be empty!{Colors.NC}")
            return create_gpg_key()
        
        print_color(Emojis.INFO, f"{Colors.CYAN}Generating a new 4096-bit RSA GPG key...{Colors.NC}")
        print_color(Emojis.LOCK, f"{Colors.YELLOW}You will be prompted to set a passphrase for your GPG key.{Colors.NC}")
        wait_for_enter()
        
        # Create batch file for GPG key generation
        batch_content = f"""%%echo Generating an RSA4096 OpenPGP key
Key-Type: RSA
Key-Length: 4096
Subkey-Type: RSA
Subkey-Length: 4096
Name-Real: {gpg_name}
Name-Email: {gpg_email}
Expire-Date: 0
%%commit
%%echo done"""
        
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.batch') as f:
            f.write(batch_content)
            batch_file = f.name
        
        try:
            print_color(Emojis.INFO, f"{Colors.CYAN}Generating key (this may take a minute while entropy is gathered)...{Colors.NC}")
            result = run_command(['gpg', '--batch', '--generate-key', batch_file])

            if result and result.returncode == 0:
                # Get the newly created key ID
                keys = get_gpg_keys()
                if keys:
                    latest_key = max(keys, key=lambda k: k['created'] if k['created'].isdigit() else '0')
                    gpg_key_id = latest_key['full_id']
                    print_color(Emojis.SUCCESS, f"{Colors.GREEN}Created new GPG key with ID: {latest_key['id']}{Colors.NC}")
                    return prompt_for_key_name(gpg_key_id)
                else:
                    print_color(Emojis.ERROR, f"{Colors.RED}Failed to retrieve new key information!{Colors.NC}")
                    return False
            else:
                print_color(Emojis.ERROR, f"{Colors.RED}Failed to create GPG key!{Colors.NC}")
                return False
        finally:
            os.unlink(batch_file)
            
    except KeyboardInterrupt:
        raise  # Re-raise to let main() handle it

def show_pass_list():
    """Show current passwords in pass store"""
    print_color(Emojis.INFO, f"{Colors.CYAN}Current passwords in pass store:{Colors.NC}")
    
    if not check_command_exists('pass'):
        print_color(Emojis.INFO, f"{Colors.YELLOW}Pass utility not installed or no password store initialized.{Colors.NC}")
        return
    
    if not os.path.exists(os.path.expanduser('~/.password-store')):
        print_color(Emojis.INFO, f"{Colors.YELLOW}No password store initialized.{Colors.NC}")
        return
    
    result = run_command(['pass', 'list'])
    if result and result.returncode == 0:
        lines = result.stdout.strip().split('\n')
        for line in lines:
            if 'Password Store' in line:
                continue
            if '──' in line or '└──' in line or '├──' in line:
                print_color(Emojis.FOLDER, f"{Colors.RED}{line}{Colors.NC}")
            else:
                print(f"  {Emojis.FOLDER} {Colors.CYAN}{line.strip()}{Colors.NC}")

def prompt_for_key_name(gpg_key_id):
    """Prompt for key name to store password"""
    print()

    password_store_path = os.path.expanduser('~/.password-store')
    if os.path.exists(password_store_path):
        show_pass_list()
        print()

    try:
        key_name = input(f"{Emojis.KEY} {Colors.PURPLE}Enter a name for the password to store (e.g., email, website): {Colors.NC}")
        
        if not key_name.strip():
            print_color(Emojis.ERROR, f"{Colors.RED}Password name cannot be empty!{Colors.NC}")
            return prompt_for_key_name(gpg_key_id)
        
        # Check if password already exists
        result = run_command(['pass', 'show', key_name])
        if result and result.returncode == 0:
            print_color(Emojis.WARNING, f"{Colors.YELLOW}A password named '{key_name}' already exists.{Colors.NC}")
            overwrite = input(f"{Emojis.REFRESH} {Colors.YELLOW}Do you want to overwrite it? (y/N): {Colors.NC}")
            if overwrite.lower() in ['y', 'yes']:
                return prompt_for_password(key_name, gpg_key_id)
            else:
                print_color(Emojis.INFO, f"{Colors.CYAN}Operation cancelled.{Colors.NC}")
                return False
        else:
            return prompt_for_password(key_name, gpg_key_id)
            
    except KeyboardInterrupt:
        raise  # Re-raise to let main() handle it

def prompt_for_password(key_name, gpg_key_id):
    """Prompt for password to store"""
    try:
        password = getpass.getpass(f"{Emojis.LOCK} {Colors.BLUE}Password to store for '{key_name}': {Colors.NC}")
        password_confirm = getpass.getpass(f"{Emojis.LOCK} {Colors.BLUE}Enter the password again: {Colors.NC}")
        
        if password != password_confirm:
            print_color(Emojis.ERROR, f"{Colors.RED}Passwords do not match!{Colors.NC}")
            return prompt_for_password(key_name, gpg_key_id)
        
        if not password:
            print_color(Emojis.ERROR, f"{Colors.RED}Password cannot be empty!{Colors.NC}")
            return prompt_for_password(key_name, gpg_key_id)
        
        return store_password(key_name, password, gpg_key_id)
        
    except KeyboardInterrupt:
        print_color(Emojis.INFO, f"{Colors.CYAN}Operation cancelled.{Colors.NC}")
        return False

def check_pass_storage():
    """Check if pass utility is available"""
    print_color(Emojis.INFO, f"{Colors.CYAN}Checking for password storage (pass utility)...{Colors.NC}")
    
    if not check_command_exists('pass'):
        print_color(Emojis.ERROR, f"{Colors.RED}Pass utility not found! Please install it first.{Colors.NC}")
        print_color(Emojis.INFO, f"{Colors.CYAN}On Debian/Ubuntu: sudo apt install pass{Colors.NC}")
        print_color(Emojis.INFO, f"{Colors.CYAN}On macOS: brew install pass{Colors.NC}")
        return False
    
    print_color(Emojis.SUCCESS, f"{Colors.GREEN}Pass utility found!{Colors.NC}")
    return True

def init_pass_if_needed(gpg_key_id):
    """Initialize pass if needed"""
    password_store_path = os.path.expanduser('~/.password-store')
    if not os.path.exists(password_store_path):
        print_color(Emojis.INFO, f"{Colors.CYAN}Initializing password store with GPG key: {gpg_key_id}{Colors.NC}")
        result = run_command(['pass', 'init', gpg_key_id])
        return result and result.returncode == 0
    return True

def store_password(key_name, password, gpg_key_id):
    """Store password in pass"""
    print()
    print_color(Emojis.INFO, f"{Colors.CYAN}Checking password storage...{Colors.NC}")
    
    if not check_pass_storage():
        return False
    
    if not init_pass_if_needed(gpg_key_id):
        print_color(Emojis.ERROR, f"{Colors.RED}Failed to initialize password store!{Colors.NC}")
        return False
    
    print_color(Emojis.INFO, f"{Colors.CYAN}Storing password for '{key_name}'...{Colors.NC}")
    
    # Use subprocess with input to pass the password
    process = subprocess.Popen(['pass', 'insert', '-e', key_name], 
                             stdin=subprocess.PIPE, 
                             stdout=subprocess.PIPE, 
                             stderr=subprocess.PIPE, 
                             text=True)
    
    stdout, stderr = process.communicate(input=password)
    
    if process.returncode == 0:
        print_color(Emojis.SUCCESS, f"{Colors.GREEN}Password successfully stored for '{key_name}'!{Colors.NC}")
        print_color(Emojis.FOLDER, f"{Colors.PURPLE}Password location: ~/.password-store/{key_name}.gpg{Colors.NC}")
        return True
    else:
        print_color(Emojis.ERROR, f"{Colors.RED}Failed to store password: {stderr.strip()}{Colors.NC}")
        return False

def confirm_quit():
    """Ask user if they want to quit"""
    try:
        response = input(f"{Emojis.WARNING} {Colors.YELLOW} Quit? <y|n>: {Colors.NC}").lower()
        return response in ['y', 'yes']
    except KeyboardInterrupt:
        return True

def main():
    """Main function"""
    try:
        #os.system('clear' if os.name == 'posix' else 'cls')
        print_color(Emojis.KEY, f"{Colors.PURPLE}=== GPG & Pass Manager ==={Colors.NC}")
        print()
        
        # Check prerequisites
        if not check_command_exists('gpg'):
            print_color(Emojis.ERROR, f"{Colors.RED}GPG is not installed! Please install it first.{Colors.NC}")
            print_color(Emojis.INFO, f"{Colors.CYAN}On Debian/Ubuntu: sudo apt install gnupg{Colors.NC}")
            print_color(Emojis.INFO, f"{Colors.CYAN}On macOS: brew install gpg{Colors.NC}")
            sys.exit(1)
        
        success = check_gpg_key()
        if not success:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print()
        if confirm_quit():
            print_color(Emojis.INFO, f"{Colors.CYAN}Goodbye!{Colors.NC}")
            sys.exit(0)
        else:
            print()
            main()  # Restart the program
    except Exception as e:
        print_color(Emojis.ERROR, f"{Colors.RED}An unexpected error occurred: {e}{Colors.NC}")
        sys.exit(1)

if __name__ == "__main__":
    main()
