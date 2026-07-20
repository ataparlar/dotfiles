# Enable Powerlevel10k instant prompt
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# Path to your Oh My Zsh installation.
export ZSH="$HOME/.oh-my-zsh"

# Set ZSH theme. If AUR version is installed, we override it later.
if [ -f /usr/share/zsh-theme-powerlevel10k/powerlevel10k.zsh-theme ]; then
  ZSH_THEME="robbyrussell"
else
  ZSH_THEME="powerlevel10k/powerlevel10k"
fi

# Plugins to load
plugins=(
  git
  bundler
  dotenv
)

source $ZSH/oh-my-zsh.sh

# Source powerlevel10k theme from AUR if present
if [ -f /usr/share/zsh-theme-powerlevel10k/powerlevel10k.zsh-theme ]; then
  source /usr/share/zsh-theme-powerlevel10k/powerlevel10k.zsh-theme
fi

# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh
POWERLEVEL9K_DISABLE_CONFIGURATION_WIZARD=true

# Load dotfiles user settings (defines system variables and active user)
if [ -f "$HOME/.user_settings.sh" ]; then
    source "$HOME/.user_settings.sh"
elif [ -f "$HOME/projects/dotfiles/user_settings.sh" ]; then
    source "$HOME/projects/dotfiles/user_settings.sh"
fi

# Source custom aliases
[ -f "$HOME/.zsh_aliases" ] && source "$HOME/.zsh_aliases"

# Vim mode in command line
bindkey -v

# Custom user paths
export PATH="$HOME/.bin:$PATH"
export PATH="$HOME/.bin/ifz_lanelet/scripts:$PATH"
export PATH="$HOME/.bin/biom_dev/scripts:$PATH"
export PATH="$HOME/.bin/gis_dev/scripts:$PATH"
export PATH="$HOME/.bin/thesis-mapping-dev/scripts:$PATH"
export PATH="$HOME/.bin/devv/scripts:$PATH"
export PATH="$HOME/.bin/fig_dev/scripts:$PATH"
export PATH="$HOME/.local/bin:$PATH"
