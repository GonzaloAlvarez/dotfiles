
function __git_ps1 {
    if [[ "$(git status 2> /dev/null | tail -n1)" == *"nothing to commit"* ]]; then
        git branch 2>/dev/null | grep '*' | sed 's/* \(.*\)/(\1)/'
    else
        git branch 2>/dev/null | grep '*' | sed 's/* \(.*\)/(\1*)/'
    fi  
}
