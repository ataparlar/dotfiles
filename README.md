# 🛠️ ataparlar Dotfiles

A clean, modular, and container-friendly dotfiles repository configured for development.

## 📂 Managed Configurations
- **Neovim (`nvim`)**: LazyVim-based structure with custom plugins including **Antigravity integration**.
- **Zsh (`zshrc`, `zsh_aliases`, `p10k.zsh`)**: Shell configs customized with Powerlevel10k theme prompts.
- **Vim (`vimrc`)**: Simple Vim configuration with system/Wayland clipboard support.
- **Git (`gitconfig`)**: User information and custom include configs.
- **GitHub CLI (`gh`)**: Custom commands and configuration profiles.

---

## 👤 Username Configuration Variable
We have created a centralized `user_settings.sh` file to define your username:
```bash
export DOTFILES_USER="devv"
```

You can reference this variable in different configurations:
- **Zsh/Shell scripts**: Use `$DOTFILES_USER` directly (e.g., `echo $DOTFILES_USER` or dynamic path structures).
- **Neovim/Lua**: Access it via `os.getenv("DOTFILES_USER")` (e.g., `local user = os.getenv("DOTFILES_USER")`).
- **Vim**: Access it using `$DOTFILES_USER`.

---

## 🚀 Installation & Update
Run the installation script to backup your existing configurations and link them to this repository:
```bash
./install.sh
```

### 🐳 Docker & Bind-Mount Support
The `install.sh` script is fully container-aware:
- If a target config file is a bind-mount (e.g. read-only file systems in containers), it will print a warning and skip modifications gracefully instead of crashing.
- Your `.zshrc` automatically includes fallbacks to source the repository files directly, ensuring configurations work even if physical symlinks cannot be made due to bind mount restrictions.
