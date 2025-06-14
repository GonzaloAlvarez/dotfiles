
function gitconfig() {
    if [ "$(git remote show origin | grep "github.com")" ]; then
        git config user.name "Gonzalo Alvarez"
        git config user.email "gonzaloab@gmail.com"
    fi
}
