EDITOR=vim
GIT_EDITOR=vim

function is_osx() {
    [[ "$OSTYPE" =~ ^darwin ]] || return 1
}

if [ -f $HOME/.hostname ]; then
    HOST_CNAME="$(head -n 1 $HOME/.hostname)"
else
    HOST_CNAME="localhost"
fi

PS1="\[\e[1;32m\]\$(__git_ps1)[\u@$HOST_CNAME \W]\$\[\e[0m\] "


# Files will be created with these permissions:
# files 644 -rw-r--r-- (666 minus 022)
# dirs  755 drwxr-xr-x (777 minus 022)
umask 022


# Less related exports
export LESS="-RSi"
export LESS_TERMCAP_so="$(printf 'rev\nbold\nsetaf 3\n' | tput -S)"
export LESS_TERMCAP_se="$(tput sgr0)"
