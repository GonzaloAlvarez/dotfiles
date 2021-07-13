#!/bin/bash 

SELF_PATH="$(cd "$(dirname "$0")" && pwd)"

function _build_paths() {
    for toplevel in $SELF_PATH/*; do
        if [ -d "$toplevel" ]; then
            toplevel_basename=$(basename $toplevel)
            echo "using $toplevel_basename"
            INCLUDE_FILES="$(find $SELF_PATH/$toplevel_basename -type f)"
            for extra_path in $@; do
                if [ -d "$extra_path/$toplevel_basename" ]; then
                    INCLUDE_FILES="$(echo $INCLUDE_FILES; find $extra_path/$toplevel_basename -type f)"
                fi
            done
            SORTED_FILES=$(for i in $INCLUDE_FILES; do echo $(basename $i) $i; done | sort | cut -d ' ' -f 2-)
            rm -Rf $HOME/$toplevel_basename
            :> $HOME/.$toplevel_basename
            for file in $SORTED_FILES; do
                echo "Adding functions file [$(basename $file)] to [$HOME/.$toplevel_basename]"
                cat $file >> $HOME/.$toplevel_basename
            done
        fi
    done
}

_build_paths $@

if [ "$(uname)" == "Darwin" ]; then
    ln -s ~/.bashrc ~/.bash_profile
fi
