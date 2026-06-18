#!/usr/bin/env python3

#!/usr/bin/env python3
import argparse
import textwrap

def create_box(orig_message, box_style=2, max_length=None):
    # Define box characters based on style
    if box_style == 1:
        top_bottom = '─'
        corners = '┌┐└┘'
        vertical = '│'
    else:
        top_bottom = '═'
        corners = '╔╗╚╝'
        vertical = '║'
    
    # Split message if max_length is specified
    if max_length and len(orig_message) > max_length:
        lines = textwrap.wrap(orig_message, max_length)
    else:
        lines = [orig_message]
    
    # Add padding after wrapping
    padded_lines = [' ' + line + ' ' for line in lines]
    
    # Calculate box width
    content_width = max(len(line) for line in padded_lines)
    
    # Create box parts
    top = f"{corners[0]}{top_bottom * content_width}{corners[1]}"
    bottom = f"{corners[2]}{top_bottom * content_width}{corners[3]}░"
    
    # Create content lines
    content = []
    for line in padded_lines:
        padded = line.ljust(content_width)
        content.append(f"{vertical}{padded}{vertical}░")
    
    # Create shadow line
    shadow_width = content_width + 1
    shadow = "  " + "░" * shadow_width
    
    # Combine all parts
    box = [top] + content + [bottom, shadow]
    
    return "\n".join(box)


def old_create_box(orig_message, box_style=2, max_length=None):
    
    message = ' ' + orig_message + ' '
    
    # Define box characters based on style
    if box_style == 1:
        top_bottom = '─'
        corners = '┌┐└┘'
        vertical = '│'
    else:
        top_bottom = '═'
        corners = '╔╗╚╝'
        vertical = '║'
    
    # Split message if max_length is specified
    if max_length and len(message) > max_length:
        lines = textwrap.wrap(message, max_length)
    else:
        lines = [message]
    
    # Calculate box width (including borders)
    content_width = max(len(line) for line in lines)
    
    # Create box parts
    top = f"{corners[0]}{top_bottom * content_width}{corners[1]}"
    bottom = f"{corners[2]}{top_bottom * content_width}{corners[3]}░"
    
    # Create content lines with proper padding
    content = []
    for line in lines:
        padded = line.ljust(content_width)
        content.append(f"{vertical}{padded}{vertical}░")
    
    shadow_width = content_width + 1  # +1 to align with the right shadow edge
    
    # Create shadow line with proper alignment
    shadow = "  " + "░" * shadow_width  # Align with content width
    
    # Combine all parts
    box = [top] + content + [bottom, shadow]
    
    return "\n".join(box)

def main():
    parser = argparse.ArgumentParser(description='Create ASCII art boxes with shadows')
    parser.add_argument('message', help='The message to box')
    parser.add_argument('-b', '--box', type=int, choices=[1, 2], default=2,
                       help='Box style (1=single line, 2=double line)')
    parser.add_argument('-m', '--maxlen', type=int,
                       help='Maximum line length before wrapping')
    
    args = parser.parse_args()
    print(create_box(args.message, args.box, args.maxlen))

if __name__ == '__main__':
    main()