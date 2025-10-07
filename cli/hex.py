#!/usr/bin/env python3

import argparse
import os
import sys

# Define ANSI escape codes for colorization
BACKGROUND_COLOR = '\033[44m'  # Blue background
FOREGROUND_COLOR = '\033[97m'  # White foreground
RESET_COLOR = '\033[0m'        # Reset to default

DEFAULT_LENGTH = 65536  # 64KB

def read_data(filename, length, skip):
    """Reads binary data from the specified file or device."""
    try:
        file_size = os.path.getsize(filename)
    except OSError as e:
        print(f"Error: Unable to determine file size: {e}", file=sys.stderr)
        sys.exit(1)

    if skip > file_size:
        raise ValueError("Skip offset is greater than file size.")
    
    with open(filename, 'rb') as f:
        f.seek(skip)
        # If length is None, default to 64KB
        if length is None:
            length = DEFAULT_LENGTH
        else:
            length = min(length, file_size - skip)
        return f.read(length)

def hexdump(filename, length, skip):
    """Generates a hexdump of the file with hexadecimal and ASCII views."""
    try:
        data = read_data(filename, length, skip)
    except (ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    hex_offset = skip
    hex_lines = []
    
    for i in range(0, len(data), 16):
        line_data = data[i:i+16]
        offset_str = f'{hex_offset:08X}'
        hex_values = ' '.join(f'{byte:02X}' for byte in line_data)
        ascii_chars = ''.join(chr(byte) if 32 <= byte <= 126 else '.' for byte in line_data)
        
        line = f"{offset_str} | {hex_values.ljust(47)} | {ascii_chars.ljust(16)} |"
        hex_lines.append(line)
        
        hex_offset += 16

    # Print the formatted hexdump with color using ANSI escape codes
    for line in hex_lines:
        print(f"{BACKGROUND_COLOR}{FOREGROUND_COLOR}{line}{RESET_COLOR}")

def main():
    parser = argparse.ArgumentParser(description='Hexdump a binary file or device with hexadecimal and ASCII views.')
    parser.add_argument('-f', '--file', required=True, help='Filename or device to read from')
    parser.add_argument('-n', '--length', type=int, default=DEFAULT_LENGTH, help='Interpret only length bytes of input (default: 64KB)')
    parser.add_argument('-s', '--skip', type=int, default=0, help='Skip offset bytes from the beginning (default: 0)')
    parser.add_argument('-V', '--version', action='version', version='Hexdump version 1.0', help='Display version')

    args = parser.parse_args()
    
    hexdump(args.file, args.length, args.skip)

if __name__ == '__main__':
    main()

