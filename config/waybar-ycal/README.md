# hypr-ycal (Waybar Ycal + Hyprland Background Task Manager)

An interactive desktop productivity suite for Wayland / Hyprland and Waybar, combining:
1. **Desktop Background Dashboard (`bg.py`)**: An always-on, interactive Google Calendar & Google Tasks dashboard running on Hyprland's background layer (`gtk4-layer-shell`).
2. **Waybar Popup Daemon (`popup.py`)**: Fast on-demand calendar & task popup invoked from the Waybar bar module.
3. **Dynamic Theme Engine (`switch-theme.sh`)**: Hot-reloading matte themes (Dark Pastel Grey-Green, Neutral Grey, Catppuccin Mocha) synchronized across both Waybar and the desktop background.

---

## Google Cloud OAuth Setup

To access your Google Calendar and Google Tasks, you need personal OAuth2 credentials from Google Cloud. This is a free, one-time setup:

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g. `waybar-ycal` or `my-desktop-calendar`).
3. **Enable APIs**: Navigate to **APIs & Services → Library**, search for and enable:
   - **Google Calendar API**
   - **Google Tasks API**
4. **Configure OAuth Consent Screen**:
   - Go to **APIs & Services → OAuth consent screen**.
   - Choose **External** user type and fill in required app info (app name, your email).
   - In **Publishing status**, set it to **In production** (or add your personal Google account under test users). Personal desktop apps do not require Google app verification.
5. **Create Credentials**:
   - Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
   - Application type: **Desktop app**.
   - Name it (e.g., `waybar-ycal-desktop`).
   - Download the JSON credentials file directly from the creation confirmation dialog.
6. **Install Credentials**:
   - Save the downloaded file as:
     ```bash
     ~/.config/waybar-ycal/credentials.json
     ```
   - An example template is provided in `credentials.json.example`.

### First-Time Authentication

When running for the first time:
- The daemon detects that OAuth authorization is needed and launches your default web browser.
- Log in and grant read/write access to Google Calendar and Google Tasks.
- The authorization token is saved securely to `~/.cache/waybar-ycal/token.json` and automatically refreshed in the background.

---

## Architecture & Components

| Component | File | Role |
|-----------|------|------|
| **Background Dashboard** | `bg.py` | Full-screen Hyprland bottom layer window rendering calendar, today's schedule, and categorized task panels with real-time editing and creation. |
| **Waybar Popup** | `popup.py` | Top layer popup widget displaying calendar grid, event badges, and interactive task toggles. |
| **Waybar Bar Module** | `bar.py` | Outputs formatted JSON with date, active events, and Nerd Font icons for Waybar. |
| **Waybar Toggle** | `toggle.sh` | Sends `SIGUSR1` to toggle the popup visibility. |
| **Theme Switcher** | `switch-theme.sh` | Switches active color palette for the background dashboard or both Waybar and dashboard using `--all`. |

---

## Systemd User Services

Both the Waybar popup and the background desktop manager run as systemd user units:

```bash
# Enable and start popup daemon
systemctl --user enable --now waybar-ycal.service

# Enable and start background dashboard
systemctl --user enable --now waybar-ycal-bg.service
```

Status check:
```bash
systemctl --user status waybar-ycal waybar-ycal-bg
```

---

## Theming

Themes are JSON definitions stored in `themes/`. Current built-in themes:
- `dark-pastel-grey-green` (Default matte palette)
- `neutral-grey`
- `catppuccin-mocha`

### Switching Themes

```bash
# Switch desktop background only
~/.config/waybar-ycal/switch-theme.sh dark-pastel-grey-green

# Switch both Waybar and desktop background synchronously
~/.config/waybar-ycal/switch-theme.sh --all dark-pastel-grey-green
```

---

## Waybar Integration

Add to `~/.config/waybar/config.jsonc`:

```jsonc
"custom/ycal": {
    "exec": "~/.config/waybar-ycal/bar.py",
    "on-click": "~/.config/waybar-ycal/toggle.sh",
    "interval": 60,
    "return-type": "json"
}
```

Include `"custom/ycal"` in your `modules-center` or desired position.

---

## Credits & Upstream

- Originally inspired by and built on top of [waybar-ycal](https://github.com/yagybaba/waybar-ycal) by [yagybaba](https://github.com/yagybaba).
- Extended with full-screen Hyprland layer-shell background task manager, multi-list task organization, inline task creation, and synchronized matte theme engine.
