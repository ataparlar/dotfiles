#!/usr/bin/env bash

set -euo pipefail

DOTFILES_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

show_help() {
    echo "=== Dotfiles Installation Entrypoint ==="
    echo "Usage:"
    echo "  ./install.sh [option]"
    echo ""
    echo "Options:"
    echo "  --soft      Only install/link configuration files (default)"
    echo "  --hard      Install system libraries (wifi, bluetooth, wayland, hyprland, etc.)"
    echo "              and then link configurations (use for new Arch installs)"
    echo "  --help      Show this help message"
}

# Default to soft install if no argument is provided
if [ $# -eq 0 ]; then
    echo "Defaulting to Soft Installation (Configs only)..."
    bash "$DOTFILES_DIR/soft_install.sh"
    exit 0
fi

case "$1" in
    --soft)
        bash "$DOTFILES_DIR/soft_install.sh"
        ;;
    --hard)
        bash "$DOTFILES_DIR/hard_install.sh"
        ;;
    --help|-h)
        show_help
        ;;
    *)
        echo "Unknown option: $1"
        show_help
        exit 1
        ;;
esac
