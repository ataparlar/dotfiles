export ZSH="$HOME/.oh-my-zsh"
ZSH_THEME="powerlevel10k/powerlevel10k"
plugins=(git)

source $ZSH/oh-my-zsh.sh

if [ -f "$HOME/projects/dotfiles/user_settings.sh" ]; then
    source "$HOME/projects/dotfiles/user_settings.sh"
fi

export PATH="$HOME/.bin/:$PATH"
[ -f "$HOME/.zsh_aliases" ] && source "$HOME/.zsh_aliases"
# source ~/powerlevel10k/powerlevel10k.zsh-theme
source ~/.p10k.zsh
POWERLEVEL9K_DISABLE_CONFIGURATION_WIZARD=true


# Added by Antigravity CLI installer
export PATH="$HOME/.local/bin:$PATH"

alias ccc="cd build && cmake .. -DCMAKE_EXPORT_COMPILE_COMMANDS=ON && make -j16 && cd .. && ./merge_compile_commands.sh"


# Added by Antigravity CLI installer
export PATH="/home/devv/.local/bin:$PATH"

# Alias
alias vimz="nvim ~/projects/dotfiles/zshrc"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"

