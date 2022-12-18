if [ -f "$HOME/.gear/commands.sh" ]; then
    source "$HOME/.gear/commands.sh"
fi

if ls $HOME/.bashrc.ext.* 1>/dev/null 2>&1; then
    for bashext in $HOME/.bashrc.ext.*; do
        source "$bashext"
    done
fi
