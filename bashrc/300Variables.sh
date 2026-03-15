EDITOR=vim
GIT_EDITOR=vim

function is_osx() {
    [[ "$OSTYPE" =~ ^darwin ]] || return 1
}

if [ -f $HOME/.hostname ]; then
    HOST_CNAME="$(head -n 1 $HOME/.hostname)"
else
    HOST_CNAME="\h"
fi

PS1="\[\e[1;32m\]\$(__git_ps1)[\u@$HOST_CNAME \W]\$\[\e[0m\] "

# Modify PATH to include local bin if it exists
if [ -d $HOME/.local/bin ]; then
    export PATH="$PATH:$HOME/.local/bin"
fi

if [ -d /opt/homebrew/bin ]; then
    export PATH="/opt/homebrew/bin:$PATH"
fi

if [ -d ~/.toolbox/bin ]; then
    export PATH="$HOME/.toolbox/bin:$PATH"
fi

if [ ! -d $HOME/bin ]; then
    mkdir "$HOME/bin"
fi
export PATH="$HOME/bin:$PATH"

if [ -d "$HOME/.asdf/shims" ]; then
    export PATH="$HOME/.asdf/shims:$PATH"
fi

if [ -d "$HOME/.gear/util" ]; then
    export PATH="$HOME/.gear/util:$PATH"
fi

# Files will be created with these permissions:
# files 644 -rw-r--r-- (666 minus 022)
# dirs  755 drwxr-xr-x (777 minus 022)
umask 022


# We live in an agentic world, and these bitches don't like my PS1
__bashrc_is_warp() { [[ "${TERM_PROGRAM:-}" == "WarpTerminal" ]]; }
__bashrc_is_cursor_agent() { [[ -n "${CURSOR_AGENT:-}" ]]; }
__bashrc_is_claude_code() { [[ -n "${CLAUDECODE:-}" ]]; }
__bashrc_lite_mode() { __bashrc_is_warp || __bashrc_is_cursor_agent || __bashrc_is_claude_code; }

if __bashrc_lite_mode; then
  PS1='\u@\h \W \$ '
  return 0
fi

case $- in
  *i*) ;;
  *) return 0 ;;
esac

# Set vim mode for shell
set -o vi

# Make less not paginate if less than one page
export LESS="-F -X $LESS"

# Tell Git to use less without pagination
export GIT_PAGER="less -F -X"

# Less related exports
export LESS="-RSi"
if [[ $- == *i* ]]; then
    export LESS_TERMCAP_so="$(printf 'rev\nbold\nsetaf 3\n' | tput -S)"
    export LESS_TERMCAP_se="$(tput sgr0)"
fi

# If you invoke the bash shell while macOS is configured to use a different shell, you'll see a message that the default interactive shell is now zsh. To silence this warning:
export BASH_SILENCE_DEPRECATION_WARNING=1
