-- NeoVIM init lua file
-- Custom commands for VSCode
-- reload with :source $MYVIMRC

-- Loading lazy.vim before mapleader
-- Bootstrap lazy.nvim
if not vim.g.vscode then
    local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
    if not (vim.uv or vim.loop).fs_stat(lazypath) then
    local lazyrepo = "https://github.com/folke/lazy.nvim.git"
    local out = vim.fn.system({ "git", "clone", "--filter=blob:none", "--branch=stable", lazyrepo, lazypath })
    if vim.v.shell_error ~= 0 then
        vim.api.nvim_echo({
        { "Failed to clone lazy.nvim:\n", "ErrorMsg" },
        { out, "WarningMsg" },
        { "\nPress any key to exit..." },
        }, true, {})
        vim.fn.getchar()
        os.exit(1)
    end
    end
    vim.opt.rtp:prepend(lazypath)
end


-- Let's start with the leader
vim.g.mapleader = ","
vim.g.maplocalleader = ","

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
vim.opt.relativenumber = true       -- Show relative numbers
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
else
    -- Setup lazy.nvim
    require("lazy").setup({
    spec = {
        { 'dasupradyumna/midnight.nvim', lazy = false, priority = 1000 },
        {'akinsho/bufferline.nvim', version = "*"},
        {'nvim-telescope/telescope.nvim', tag = '0.1.8', dependencies = { 'nvim-lua/plenary.nvim' }},
        "lewis6991/gitsigns.nvim",
        "nvim-lualine/lualine.nvim",
        { "nvim-tree/nvim-tree.lua", version = "*", lazy = false},
    },
    -- colorscheme that will be used when installing plugins.
    install = { colorscheme = { "habamax" } },
    -- automatically check for plugin updates
    checker = { enabled = false },
    })

    -- nvim tree configuration
    require("nvim-tree").setup({
        sort_by = "case_sensitive",
        hijack_cursor = true,
        update_focused_file = {
            update_root = true,
        },
        view = {
            signcolumn = "auto",
        },
        actions = {
            open_file = {
                quit_on_open = true,
            },
        },
        renderer = {
            group_empty = true,
            icons = {
                show = {
                    file = false,
                    folder = false,
                },
                glyphs = {
                    bookmark = "🔖",
                    folder = {
                        arrow_closed = "⏵",
                        arrow_open = "⏷",
                    },
                    symlink = "",
                    git = {
                        unstaged = "✗",
                        staged = "✓",
                        unmerged = "⌥",
                        renamed = "➜",
                        untracked = "☆",
                        deleted = "⊖",
                        ignored = "◌",
                    },
                },
            },
        },
        filters = {
            dotfiles = true,
        },
    })

    -- Set statusbar
    require('lualine').setup({
        options = {
            icons_enabled = false,
            theme = 'onedark',
            component_separators = '|',
            section_separators = '',
        },
    })

    -- Bufferline
    require("bufferline").setup{
        options = {
            indicator = { style = "icon", icon = "▎"},
            modified_icon = "●",
            show_close_icon = false,
            show_buffer_close_icons = false,
            always_show_bufferline = false,
            show_tab_indicators = true,
        },
        highlights = {
            fill = {
                fg = { attribute = "fg", highlight = "Visual" },
                bg = { attribute = "bg", highlight = "TabLine" },
            },
            background = {
                fg = { attribute = "fg", highlight = "TabLine" },
                bg = { attribute = "bg", highlight = "TabLine" },
            },
            modified = {
                fg = { attribute = "fg", highlight = "TabLine" },
                bg = { attribute = "bg", highlight = "TabLine" },
            },
            modified_selected = {
                fg = { attribute = "fg", highlight = "Normal" },
                bg = { attribute = "bg", highlight = "Normal" },
            },
            modified_visible = {
                fg = { attribute = "fg", highlight = "TabLine" },
                bg = { attribute = "bg", highlight = "TabLine" },
            },
            indicator_selected = {
                fg = { attribute = "fg", highlight = "LspDiagnosticsDefaultHint" },
                bg = { attribute = "bg", highlight = "Normal" },
            },
        },
    }

    local function open_nvim_tree()
        require("nvim-tree.api").tree.open()
    end
    vim.keymap.set('n', '<leader>t', ':NvimTreeToggle<CR>', {noremap = true})

    vim.cmd([[colorscheme midnight]])

    -- keybindings conflicting with vscode
    vim.keymap.set('n', 'J', '<PageDown>')
    vim.keymap.set('n', 'K', '<PageUp>')

    -- Buffer navigation keybindings
    vim.keymap.set('n', '<leader><Tab>', ':bnext<CR>')
    vim.keymap.set('n', '<leader><S-Tab>', ':bprevious<CR>')
    vim.keymap.set('n', '<leader>q', ':bd<CR>')
    vim.keymap.set('n', '<leader>Q', ':%bd|e#|bd#<CR>')

    -- Telescope
    local builtin = require('telescope.builtin')
    vim.keymap.set('n', '<leader>ff', builtin.find_files, { desc = 'Telescope find files' })
    vim.keymap.set('n', '<leader>fg', builtin.live_grep, { desc = 'Telescope live grep' })
    vim.keymap.set('n', '<leader>fb', builtin.buffers, { desc = 'Telescope buffers' })
    vim.keymap.set('n', '<leader>fh', builtin.help_tags, { desc = 'Telescope help tags' })
end
