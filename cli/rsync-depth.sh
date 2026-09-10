#!/bin/bash
# ==============================================================================
# rsync-max-depth.sh
#
#   Provides a menu for planning depth-specific rsync ops between a src and dest
#
#   - Limits directory traversal depth using include/exclude globs
#   - Modify run flags for different purposes (destination chown or whatever)
#   - Preview what will happen with a 'dry run'
#   - Color because Gemini was involed
# ==============================================================================

set -euo pipefail

COLOR_RESET="\033[0m"
COLOR_CYAN="\033[36m"
COLOR_YELLOW="\033[33m"
COLOR_MAGENTA="\033[35m"

if [ "$#" -ne 2 ]; then
  printf "${COLOR_CYAN}Usage: %s <src> <dest>${COLOR_RESET}\n" "$0"
  exit 1
fi

SOURCE_DIR="$1"
DEST_DIR="$2"

DEPTH_LIMIT=1
RSYNC_FLAGS="-a"

generate_exclude_pattern() {
  local depth="$1"
  local pattern="/*"
  local index

  for ((index = 0; index < depth; index++)); do
    pattern="${pattern}/*"
  done

  echo "$pattern"
}

build_rsync_command() {
  local dry_run_flag="$1"
  local exclude_pattern
  exclude_pattern=$(generate_exclude_pattern "$DEPTH_LIMIT")

  local command_array=("rsync" "$RSYNC_FLAGS")

  if [ -n "$dry_run_flag" ]; then
    command_array+=("$dry_run_flag")
  fi

  command_array+=("--include=/*/" "--include=/*" "--exclude=${exclude_pattern}" "$SOURCE_DIR" "$DEST_DIR")

  echo "${command_array[@]}"
}

display_menu() {
  printf "\n"
  printf "${COLOR_YELLOW}1)${COLOR_RESET} ${COLOR_CYAN}set depth limit${COLOR_RESET} ${COLOR_CYAN}(Current:${COLOR_RESET} ${COLOR_MAGENTA}%s${COLOR_RESET}${COLOR_CYAN})${COLOR_RESET}\n" "$DEPTH_LIMIT"
  printf "${COLOR_YELLOW}2)${COLOR_RESET} ${COLOR_CYAN}set rsync flags${COLOR_RESET} ${COLOR_CYAN}(Current:${COLOR_RESET} ${COLOR_MAGENTA}%s${COLOR_RESET}${COLOR_CYAN})${COLOR_RESET}\n" "$RSYNC_FLAGS"
  printf "${COLOR_YELLOW}3)${COLOR_RESET} ${COLOR_CYAN}view a dry run${COLOR_RESET}\n"
  printf "${COLOR_YELLOW}4)${COLOR_RESET} ${COLOR_CYAN}execute${COLOR_RESET}\n"
  printf "${COLOR_CYAN}Selection:${COLOR_RESET} "
}

while true; do
  display_menu
  read -r selection

  case "$selection" in
    1)
      printf "${COLOR_CYAN}Enter depth limit (integer >= 1):${COLOR_RESET} "
      read -r input_depth
      if [[ "$input_depth" =~ ^[1-9][0-9]*$ ]]; then
        DEPTH_LIMIT="$input_depth"
      else
        printf "${COLOR_CYAN}Error: Depth limit must be a positive integer.${COLOR_RESET}\n"
      fi
      ;;
    2)
      printf "${COLOR_CYAN}Current rsync flags:${COLOR_RESET} ${COLOR_MAGENTA}%s${COLOR_RESET}\n" "$RSYNC_FLAGS"
      printf "${COLOR_CYAN}Enter additional or replacement flags:${COLOR_RESET} "
      read -r input_flags
      if [ -n "$input_flags" ]; then
        RSYNC_FLAGS="$input_flags"
      fi
      ;;
    3)
      printf "${COLOR_CYAN}Executing dry run...${COLOR_RESET}\n"
      generated_command=$(build_rsync_command "--dry-run")
      printf "${COLOR_CYAN}Command:${COLOR_RESET} ${COLOR_MAGENTA}%s${COLOR_RESET}\n" "$generated_command"
      eval "$generated_command"
      ;;
    4)
      printf "${COLOR_CYAN}Executing transfer...${COLOR_RESET}\n"
      generated_command=$(build_rsync_command "")
      printf "${COLOR_CYAN}Command:${COLOR_RESET} ${COLOR_MAGENTA}%s${COLOR_RESET}\n" "$generated_command"
      eval "$generated_command"
      exit 0
      ;;
    *)
      printf "${COLOR_CYAN}Invalid selection.${COLOR_RESET}\n"
      ;;
  esac
done
