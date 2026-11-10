#!/bin/bash
# Waybar Theme Switcher
# Usage:
#   switch-theme.sh                    (list available themes & active theme)
#   switch-theme.sh <theme-name>       (switch to theme and reload waybar)

WAYBAR_DIR="$HOME/.config/waybar"
THEMES_DIR="$WAYBAR_DIR/themes"
CURRENT_FILE="$WAYBAR_DIR/.current-theme"
TARGET_STYLE="$WAYBAR_DIR/style.css"

list_themes() {
    echo "=========================================="
    echo "  Waybar Theme Switcher"
    echo "=========================================="
    active="unknown"
    if [ -f "$CURRENT_FILE" ]; then
        active=$(cat "$CURRENT_FILE")
    fi
    echo "Active Theme: $active"
    echo ""
    echo "Available Themes:"
    for f in "$THEMES_DIR"/*.css; do
        if [ -f "$f" ]; then
            tname=$(basename "$f" .css)
            if [ "$tname" = "$active" ]; then
                echo "  * $tname (active)"
            else
                echo "    $tname"
            fi
        fi
    done
    echo ""
    echo "To switch theme:"
    echo "  $0 <theme-name>"
    echo "  $0 <theme-name> --all   (also switch desktop task manager)"
    echo "=========================================="
}

SYNC_ALL=0
THEME_NAME=""

for arg in "$@"; do
    case "$arg" in
        --all|-a)
            SYNC_ALL=1
            ;;
        -h|--help)
            list_themes
            exit 0
            ;;
        *)
            if [ -z "$THEME_NAME" ]; then
                THEME_NAME="$arg"
            fi
            ;;
    esac
done

if [ -z "$THEME_NAME" ]; then
    list_themes
    exit 0
fi

# Strip .css extension if provided
THEME_NAME="${THEME_NAME%.css}"
THEME_SRC="$THEMES_DIR/${THEME_NAME}.css"

if [ ! -f "$THEME_SRC" ]; then
    echo "Error: Theme '$THEME_NAME' not found in $THEMES_DIR"
    echo ""
    list_themes
    exit 1
fi

# Apply theme by copying to style.css
cp "$THEME_SRC" "$TARGET_STYLE"
echo "$THEME_NAME" > "$CURRENT_FILE"

# Signal Waybar to reload styles dynamically
if killall -SIGUSR2 waybar 2>/dev/null; then
    echo "Applied theme '$THEME_NAME' and reloaded Waybar successfully."
else
    echo "Applied theme '$THEME_NAME'. (Waybar is not currently running)"
fi

# Sync with waybar-ycal if requested
if [ "$SYNC_ALL" -eq 1 ]; then
    YCAL_SWITCHER="$HOME/.config/waybar-ycal/switch-theme.sh"
    if [ -x "$YCAL_SWITCHER" ]; then
        case "$THEME_NAME" in
            neutral-dark-grey)
                "$YCAL_SWITCHER" dark-pastel-grey-green
                ;;
            catppuccin-mocha)
                "$YCAL_SWITCHER" catppuccin-mocha
                ;;
        esac
    fi
fi
