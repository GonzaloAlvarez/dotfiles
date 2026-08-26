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
    if fzf --bash >/dev/null 2>&1; then
        eval "$(fzf --bash)"
    else
        __fzf_prefix="$(dirname "$(dirname "$(command -v fzf)")")"
        for __fzf_f in \
            "$__fzf_prefix/share/fzf/key-bindings.bash" \
            "$__fzf_prefix/share/fzf/completion.bash" \
            "$__fzf_prefix/opt/fzf/shell/key-bindings.bash" \
            "$__fzf_prefix/opt/fzf/shell/completion.bash" \
            "$__fzf_prefix/share/doc/fzf/examples/key-bindings.bash" \
            "$__fzf_prefix/share/bash-completion/completions/fzf"; do
            [ -f "$__fzf_f" ] && source "$__fzf_f"
        done
        unset __fzf_prefix __fzf_f
    fi
fi
