-- NeoVIM init lua file
-- Custom commands for VSCode
-- reload with :source $MYVIMRC

-- Let's start with the leader
vim.g.mapleader = ","

-- ** COMMON OPTIONS **
-- Tab Options
vim.opt.tabstop = 4
vim.opt.shiftwidth = 4
vim.opt.expandtab = true
vim.opt.softtabstop = 4

-- General options
vim.opt.title = true                -- Update window title on file change
vim.opt.scrolloff = 3               -- Keep three lines of buffer when scrolling
vim.opt.sidescrolloff = 3
vim.opt.incsearch = true            -- Incremental search
vim.opt.hlsearch = true             -- Highlight search results
vim.opt.smartcase = true            -- Search is case-sensitive only if search contains upper case
vim.opt.number = true               -- Show line numbers
vim.opt.showcmd = true              -- Display commands in the statusline
vim.opt.ruler = true                -- Show current line number in statusline
vim.opt.ttyfast = true              -- It's ok vim, our terminal is fast
vim.opt.hidden = true               -- Allow hiding of hidden buffers
vim.opt.smartindent = true          -- Auto smart indent
vim.opt.backspace = { "indent", "eol", "start" } -- Allow backspace to delete previous character in insert mode

-- Wildmenu
vim.opt.wildmenu = true
vim.opt.wildmode = "longest:full,list"
vim.opt.wildignore = { "*.swp", "*.bak", "*.o", "*.pyc", "*.class", "*~" }
vim.opt.wildignorecase = true

-- ** MAPPINGS **
-- Show/hide hidden chars
vim.keymap.set('n', '<leader>l', ':set nolist!<CR>', { silent = true })

-- Disable highlight when I finished searching
vim.keymap.set('n', '<leader>/', ':nohlsearch<CR>', { silent = true })

-- Keep visual lines enabled when identing
vim.keymap.set('v', '>', '>gv')
vim.keymap.set('v', '<', '<gv')

-- Autocomplete parenthesis, brackets and braces
vim.keymap.set('v', '(', 's()<Esc>P')
vim.keymap.set('v', '[', 's[]<Esc>P')
vim.keymap.set('v', '{', 's{}<Esc>P')

-- Kill arrow keys
vim.keymap.set('n', '<Up>', '<NOP>')
vim.keymap.set('n', '<Down>', '<NOP>')
vim.keymap.set('n', '<Left>', '<NOP>')
vim.keymap.set('n', '<Right>', '<NOP>')

if vim.g.vscode then
    vim.keymap.set('n', '<leader><Tab>', '<Cmd>call VSCodeNotify("workbench.action.nextEditor")<CR>', { silent = true })
    vim.keymap.set('n', '<leader><S-Tab>', '<Cmd>call VSCodeNotify("workbench.action.previousEditor")<CR>', { silent = true })
    vim.keymap.set('n', '<leader>q', '<Cmd>call VSCodeNotify("workbench.action.closeActiveEditor")<CR>', {noremap = true})
    vim.keymap.set('n', '<leader>oi', '<Cmd>call VSCodeNotify("editor.action.organizeImports")<CR>', {noremap = true})
    vim.keymap.set('n', '<leader>z', '<Cmd>call VSCodeNotify("workbench.action.toggleZenMode")<CR>', {noremap = true})
    vim.keymap.set('n', '<leader>t', '<Cmd>call VSCodeNotify("workbench.view.explorer")<CR>', {noremap = true})
    vim.keymap.set('n', '<leader>h', '<Cmd>call VSCodeNotify("editor.action.showHover")<CR>', {noremap = true})
    vim.keymap.set('n', '<leader>x', '<Cmd>call VSCodeNotify("workbench.action.terminal.toggleTerminal")<CR>', {noremap = true})
    vim.keymap.set('n', '<leader>pc', '<Cmd>call VSCodeNotify("workbench.view.scm")<CR>', {noremap = true})
    vim.keymap.set('n', '<leader>pr', '<Cmd>call VSCodeNotify("workbench.view.extension.github-pull-requests")<CR>', {noremap = true})
end