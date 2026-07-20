
export ZSH="$HOME/.oh-my-zsh"

ZSH_THEME="robbyrussell"

plugins=(
  git
  bundler
  dotenv
)

source $ZSH/oh-my-zsh.sh

# Enable Powerlevel10k instant prompt
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# Source the theme installed via AUR
source /usr/share/zsh-theme-powerlevel10k/powerlevel10k.zsh-theme

# To customize prompt, run `p10k configure`
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh

# Your custom aliases
alias hconf="nvim ~/.config/hypr/hyprland.conf"
alias wayconf="nvim ~/.config/waybar/config.jsonc"
alias waystyle="nvim ~/.config/waybar/style.css"


# Force the bridge between Intel (card1) and NVIDIA (card2)
export WLR_DRM_DEVICES=/dev/dri/card1:/dev/dri/card2

# Get into containers
alias ataparlar-dev='docker exec -it ataparlar-dev zsh'
alias arch-dev='docker exec -it arch_dev zsh'

alias rld='killall waybar && hyprctl reload'

alias figserver='ssh ataparlar@204.168.181.37'

export XDG_SCREENSHOTS_DIR="/home/ataparlar/Pictures/screenshots"

bindkey -v
export PATH="/home/ataparlar/.bin/ifz_lanelet/scripts:$PATH"
export PATH="/home/ataparlar/.bin/biom_dev/scripts:$PATH"
export PATH="/home/ataparlar/.bin/gis_dev/scripts:$PATH"
export PATH="/home/ataparlar/.bin/thesis-mapping-dev/scripts:$PATH"
export PATH="$HOME/.bin/fig_dev/scripts:$PATH"

# Added by Antigravity CLI installer
export PATH="/home/ataparlar/.local/bin:$PATH"
export PATH="/home/ataparlar/.bin/devv/scripts:$PATH"
export PATH="/home/ataparlar/.bin/devv-ros/scripts:$PATH"
export PATH="/home/ataparlar/.bin/fig_dev/scripts:$PATH"