if [ -f "$HOME/.gear/commands.sh" ]; then
    source "$HOME/.gear/commands.sh"
fi

if command -v brew >/dev/null 2>&1; then
    if [ -f "$(brew --prefix asdf)/libexec/asdf.sh" ]; then
        source "$(brew --prefix asdf)/libexec/asdf.sh"
    fi
fi

if ls $HOME/.bashrc.ext.* 1>/dev/null 2>&1; then
    for bashext in $HOME/.bashrc.ext.*; do
        source "$bashext"
    done
fi

if command -v fzf >/dev/null 2>&1; then
    eval "$(fzf --bash)"
fi
