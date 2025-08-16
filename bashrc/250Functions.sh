# Aider with a git branch before
baider() {
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        default_branch="branch-$(date +%Y%m%d)"
        read -p "Enter branch name [${default_branch}]: " branch_name
        branch_name="${branch_name:-$default_branch}"
        git checkout -b "$branch_name" || return 1
    fi
    aider "$@"
}
