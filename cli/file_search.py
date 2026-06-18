#!/usr/bin/env python3

import os
import argparse

class FILE_OBJ:
    def __init__(self, path, size, filename, is_found, target):
        self.path = path
        self.size = size
        self.filename = filename
        self.is_found = is_found
        self.target = target

def search_file_content(file_path, keyword, debug_mode):
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read().lower()
            if debug_mode:
               print (f"content: {content}")
            return keyword.lower() in content
    except (UnicodeDecodeError, PermissionError):
        return False


def scan_files(directory, keyword, filter_found, debug_mode):
    file_objects = []
    for foldername, subfolders, filenames in os.walk(directory):
        for filename in filenames:
            file_path = os.path.join(foldername, filename)
            size = os.path.getsize(file_path)
            is_found = search_file_content(file_path, keyword, debug_mode)
            if not filter_found or (filter_found and is_found):
                file_obj = FILE_OBJ(path=file_path, size=size, filename=filename, is_found=is_found, target=keyword)
                file_objects.append(file_obj)
    return file_objects

def print_colored_file_obj(file_obj, filter_found, debug_mode):
    """
    Print file object details with color formatting.
    If filter_found is True, only display files where is_found == True.
    The 'is_found' value is shown in bright green if True, silver if False.
    """

    # Skip printing if -f option is active and the keyword wasn't found
    if filter_found and not file_obj.is_found:
        return

    # Choose color based on whether keyword was found
    found_color = "\033[92m" if file_obj.is_found else "\033[90m"  # bright green or silver

    print(f"\033[36mPath: {found_color}{file_obj.path}\033[0m")
    print(f"\033[32mFilename: \033[0m{file_obj.filename}")
    print(f"\033[32mSize: \033[0m{file_obj.size} bytes")
    print(f"\033[32mKeyword Found: {found_color}{file_obj.is_found}\033[0m")
    print(f"\033[32mTarget Keyword: \033[0m{file_obj.target}")
    print()

def main():
    parser = argparse.ArgumentParser(description="Search for a keyword in files under the current directory.")
    parser.add_argument('-k', '--keyword', required=True, help="Keyword to search for in files.")
    parser.add_argument('-f', '--filter-found', action='store_true', help="Only print FILE_OBJ entries where is_found is True.")
    parser.add_argument('-d', '--debug-mode', action='store_true', help="print lines read if True.")
    args = parser.parse_args()

    print (f"filter_found {args.filter_found}")
    current_directory = os.getcwd()
    file_objects = scan_files(current_directory, args.keyword, args.filter_found, args.debug_mode)

    for file_obj in file_objects:
        print_colored_file_obj(file_obj, args.filter_found, args.debug_mode)

if __name__ == "__main__":
    main()

