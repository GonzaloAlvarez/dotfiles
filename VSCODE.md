# Setting up VSCode

## Install vscode using brew, and install neovim alongside

```shell
$ brew install visual-studio-code@insiders neovim
```

## Copy the configuration

```shell
$ cp -Rv config/nvim ~/.config/nvim
```

You have to manually copy the settins and keybindings.json in vscode

## Install the extensions

You have to install the following extensions in VSCode

- VSCode Neovim
- Material Icon Them
- Pitch Black Theme
- Python
- Continue [Home]
- Github Copilot [Work]

## Disable Mac Key Repeat

Otherwise you can't make the key movements natural

```shell
$ defaults write NSGlobalDomain ApplePressAndHoldEnabled -bool false
```
