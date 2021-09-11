if [ -f "$HOME/.gear/commands.sh" ]; then
    source "$HOME/.gear/commands.sh"
fi

for bashext in $HOME/.bashrc.ext.*; do
    source "$bashext"
done
