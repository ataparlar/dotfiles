#!/usr/bin/env bash

set -euo pipefail

# Avoid running as root directly
if [ "$EUID" -eq 0 ]; then
    echo "ERROR: Please do not run this script as root/sudo directly."
    echo "It will prompt you for your sudo password when executing pacman commands."
    exit 1
fi

echo "=== Dotfiles Hard Installation (Arch System + Configs) ==="

# Check if Arch Linux
if [ ! -f /etc/arch-release ]; then
    echo "ERROR: This script is only supported on Arch Linux."
    exit 1
fi

# 1. Install official pacman packages
OFFICIAL_PKGS=(
    # Base development & shell
    "base-devel"
    "git"
    "zsh"
    "cmake"
    "vim"
    "neovim"

    # Wayland & Hyprland environment
    "hyprland"
    "hypridle"
    "hyprlock"
    "wayland"
    "xorg-xwayland"
    "qt5-wayland"
    "qt6-wayland"
    
    # Portals for screensharing & file dialogs
    "xdg-desktop-portal-hyprland"
    "xdg-desktop-portal-gtk"
    
    # UI Elements & Terminals
    "waybar"
    "wofi"
    "thunar"
    "alacritty"
    "kitty"
    
    # Audio setup
    "pipewire"
    "pipewire-pulse"
    "pipewire-alsa"
    "wireplumber"
    
    # CLI Utilities
    "brightnessctl"
    "playerctl"
    "grim"
    "slurp"
    "swappy"
    "wl-clipboard"
    
    # Network & Bluetooth
    "networkmanager"
    "network-manager-applet"
    "bluez"
    "bluez-utils"
    "blueman"

    # Crucial System Desktop helpers (Notification, Authentication & User directories)
    "dunst"
    "hyprpolkitagent"
    "xdg-user-dirs"

    # Additional Desktop Utilities
    "hyprpaper"
    "wlsunset"
    "pavucontrol"
)

echo "Updating system package databases..."
sudo pacman -Sy

echo "Installing official packages..."
sudo pacman -S --needed --noconfirm "${OFFICIAL_PKGS[@]}"

# 2. Enable system services
echo "Enabling and starting NetworkManager..."
sudo systemctl enable --now NetworkManager

echo "Enabling and starting Bluetooth..."
sudo systemctl enable --now bluetooth

# 3. Install Oh My Zsh
if [ ! -d "$HOME/.oh-my-zsh" ]; then
    echo "Installing Oh My Zsh..."
    RUNZSH=no KEEP_ZSHRC=yes sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" || true
else
    echo "✓ Oh My Zsh is already installed."
fi

# 4. Install yay (AUR Helper) if not present
if ! command -v yay &> /dev/null; then
    echo "Installing yay (AUR helper)..."
    git clone https://aur.archlinux.org/yay-bin.git /tmp/yay-bin
    (cd /tmp/yay-bin && makepkg -si --noconfirm)
    rm -rf /tmp/yay-bin
else
    echo "✓ yay AUR helper is already installed."
fi

# 5. Install AUR packages
echo "Installing AUR packages..."
yay -S --needed --noconfirm zsh-theme-powerlevel10k-git ttf-meslo-nerd-font-powerlevel10k nwg-look wifi-manager-git

# 6. Initialize and configure Hyprland Package Manager (hyprpm) for plugins (like hy3)
if command -v hyprpm &> /dev/null; then
    echo "Configuring Hyprland plugins..."
    hyprpm update || true
    hyprpm add https://github.com/outfoxxed/hy3 || true
    hyprpm enable hy3 || true
else
    echo "⚠️ hyprpm not found. Hyprland plugins was not set up automatically."
fi

# 7. Initialize standard user directories and screenshot directory
echo "Configuring standard user directories..."
xdg-user-dirs-update || true
mkdir -p "$HOME/Pictures/screenshots"

# 8. Run soft install to link configs
DOTFILES_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
if [ -f "$DOTFILES_DIR/soft_install.sh" ]; then
    echo "Running soft installer to symlink configurations..."
    bash "$DOTFILES_DIR/soft_install.sh"
else
    echo "ERROR: soft_install.sh not found in $DOTFILES_DIR"
    exit 1
fi

echo "=== Hard Installation Complete! Please restart your terminal/session. ==="
