#!/bin/bash 

SELF_PATH="$(cd "$(dirname "$0")" && pwd)"
TARGET_BASHRC="$HOME/.bashrc"
HOSTNAME_FILE="$HOME/.hostname"
TMUX_CONF="$HOME/.tmux.conf"

function _die {
    echo "$@" >&2
    exit 1
}

function _build_bash {
    echo "Building bash environment"
    echo -e "#!/bin/bash\n" > $TARGET_BASHRC
    for i in $SELF_PATH/bash/functions/*.sh; do
        echo "Adding functions file [$(basename $i)]"
        cat $i >> $TARGET_BASHRC
        echo "" >> $TARGET_BASHRC
    done
    for i in $SELF_PATH/bash/*.sh; do
        echo "Adding source file [$(basename $i)]"
        cat $i >> $TARGET_BASHRC
        echo "" >> $TARGET_BASHRC
    done
    echo "Finished building bash environment"
}

if [ "$1" ]; then
    echo "$1" > $HOSTNAME_FILE
fi

_build_bash
cp -v "$SELF_PATH/tmux/tmux.conf" "$TMUX_CONF"
