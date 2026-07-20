#!/usr/bin/env bash

set -euo pipefail

# Get the absolute path to the dotfiles directory
DOTFILES_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
BACKUP_DIR="$HOME/.dotfiles.backup_$(date +%Y%m%d_%H%M%S)"

echo "=== Dotfiles Installation Script ==="
echo "Dotfiles source: $DOTFILES_DIR"

backup_and_link() {
    local src="$1"
    local dest="$2"

    # Resolve destination's parent directory and ensure it exists
    local dest_dir
    dest_dir="$(dirname "$dest")"
    mkdir -p "$dest_dir"

    # Check if the destination exists
    if [ -e "$dest" ] || [ -L "$dest" ]; then
        # Check if it is already a symlink pointing to the correct source file
        if [ -L "$dest" ] && [ "$(readlink -f "$dest")" = "$(readlink -f "$src")" ]; then
            echo "✓ $dest is already correctly linked."
            return
        fi

        # Otherwise, backup existing file/directory
        echo "Backing up existing $dest to $BACKUP_DIR..."
        mkdir -p "$BACKUP_DIR"
        # Recreate parent directories in backup folder to maintain structure
        local relative_path="${dest#$HOME/}"
        # If relative_path starts with a slash (or is absolute), clean it up
        relative_path="${relative_path#/}"
        mkdir -p "$(dirname "$BACKUP_DIR/$relative_path")"
        # Copy to backup and then remove (safer in Docker overlayfs than mv)
        cp -a "$dest" "$BACKUP_DIR/$relative_path"
        if ! rm -rf "$dest" 2>/dev/null; then
            echo "⚠️ Cannot remove $dest (it might be a bind mount). Truncating file instead..."
            if ! : > "$dest" 2>/dev/null; then
                echo "⚠️ Cannot truncate $dest (Read-only file system)."
            fi
        fi
    fi

    # Create the symlink
    echo "Creating symlink: $dest -> $src"
    if ! ln -s "$src" "$dest" 2>/dev/null; then
        echo "⚠️ Failed to create symlink for $dest (device/resource busy or bind mount). Writing fallback redirection instead..."
        if [[ "$dest" == *zsh* || "$dest" == *bash* || "$dest" == *profile* || "$dest" == *aliases* ]]; then
            if ! echo "# Fallback redirection to dotfiles" > "$dest" 2>/dev/null; then
                echo "⚠️ Cannot write redirection to $dest (Read-only file system)."
            else
                echo "source \"$src\"" >> "$dest"
                echo "✓ Successfully set fallback sourcing in $dest"
            fi
        elif [[ "$dest" == *vimrc ]]; then
            if ! echo "\" Fallback redirection to dotfiles" > "$dest" 2>/dev/null; then
                echo "⚠️ Cannot write redirection to $dest (Read-only file system)."
            else
                echo "source $src" >> "$dest"
                echo "✓ Successfully set fallback sourcing in $dest"
            fi
        elif [[ "$dest" == *gitconfig ]]; then
            if ! echo "[include]" > "$dest" 2>/dev/null; then
                echo "⚠️ Cannot write redirection to $dest (Read-only file system)."
            else
                echo "    path = $src" >> "$dest"
                echo "✓ Successfully set fallback inclusion in $dest"
            fi
        else
            echo "⚠️ Failed to symlink or fallback redirect for $dest. Skipping..."
        fi
    fi
}

# Link files
backup_and_link "$DOTFILES_DIR/zshrc" "$HOME/.zshrc"
backup_and_link "$DOTFILES_DIR/zsh_aliases" "$HOME/.zsh_aliases"
backup_and_link "$DOTFILES_DIR/p10k.zsh" "$HOME/.p10k.zsh"
backup_and_link "$DOTFILES_DIR/vimrc" "$HOME/.vimrc"
backup_and_link "$DOTFILES_DIR/gitconfig" "$HOME/.gitconfig"
backup_and_link "$DOTFILES_DIR/config/nvim" "$HOME/.config/nvim"
backup_and_link "$DOTFILES_DIR/config/gh/config.yml" "$HOME/.config/gh/config.yml"

echo "=== Dotfiles installation complete! ==="
