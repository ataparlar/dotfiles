local M = {}

M.config = {
  border = "rounded",
}

function M.setup(opts)
  M.config = vim.tbl_deep_extend("force", M.config, opts or {})
end

-- Find all git repositories inside the current working directory recursively
local function find_git_repos()
  local cwd = vim.fn.getcwd()
  local excludes = {
    "node_modules",
    ".venv",
    "venv",
    "env",
    "target",
    "build",
    "dist",
    ".cache",
    ".cargo",
    ".rustup",
    ".next",
    ".idea",
    ".vscode",
  }
  local exclude_parts = {}
  for _, ext in ipairs(excludes) do
    table.insert(exclude_parts, "-name " .. vim.fn.shellescape(ext) .. " -prune")
  end
  local cmd = "find " .. vim.fn.shellescape(cwd) .. " -name .git -print -prune"
  if #exclude_parts > 0 then
    cmd = cmd .. " -o " .. table.concat(exclude_parts, " -o ")
  end

  local handle = io.popen(cmd)
  if not handle then
    return {}
  end
  local result = handle:read("*a")
  handle:close()

  local repos = {}
  for path in string.gmatch(result, "[^\r\n]+") do
    local repo_root = vim.fn.fnamemodify(path, ":h")
    table.insert(repos, repo_root)
  end

  table.sort(repos)
  return repos
end

-- Present the user with a list of git repositories to select from
local function select_repo(repos, callback)
  -- Try to load telescope if it's not loaded
  pcall(function()
    require("lazy").load({ plugins = { "telescope.nvim" } })
  end)

  local ok, telescope = pcall(require, "telescope")
  if ok then
    local pickers = require("telescope.pickers")
    local finders = require("telescope.finders")
    local conf = require("telescope.config").values
    local actions = require("telescope.actions")
    local action_state = require("telescope.actions.state")

    pickers.new({}, {
      prompt_title = "Select Git Repository",
      finder = finders.new_table {
        results = repos,
        entry_maker = function(entry)
          local display = vim.fn.fnamemodify(entry, ":~")
          return {
            value = entry,
            display = display,
            ordinal = display,
          }
        end,
      },
      sorter = conf.generic_sorter({}),
      attach_mappings = function(prompt_bufnr, map)
        actions.select_default:replace(function()
          actions.close(prompt_bufnr)
          local selection = action_state.get_selected_entry()
          if selection then
            callback(selection.value)
          end
        end)
        return true
      end,
    }):find()
  else
    -- Fallback to standard vim.ui.select
    vim.ui.select(repos, {
      prompt = "Select Git Repository:",
      format_item = function(item)
        return vim.fn.fnamemodify(item, ":~")
      end,
    }, function(choice)
      if choice then
        callback(choice)
      end
    end)
  end
end

-- Open the combined Git dashboard (GitGraph and Neogit) for a specific repo
local function open_dashboard(repo_path)
  -- Load plugins
  pcall(function()
    require("lazy").load({ plugins = { "gitgraph.nvim", "neogit" } })
  end)

  -- Create a new tab page
  vim.cmd("tabnew")
  
  -- Set local tab directory to the selected repo path
  vim.cmd("tcd " .. vim.fn.fnameescape(repo_path))

  local gg_win = vim.api.nvim_get_current_win()
  local gg_buf = vim.api.nvim_get_current_buf()

  -- Setup GitGraph buffer
  vim.bo[gg_buf].buftype = "nofile"
  vim.bo[gg_buf].bufhidden = "wipe"
  vim.bo[gg_buf].swapfile = false

  -- Draw GitGraph in this window
  require("gitgraph").draw({}, { all = true, max_count = 5000 })

  -- Update gg_buf to refer to the actual GitGraph buffer created by draw()
  gg_buf = vim.api.nvim_get_current_buf()
  vim.bo[gg_buf].buftype = "nofile"
  vim.bo[gg_buf].bufhidden = "wipe"
  vim.bo[gg_buf].swapfile = false

  -- Map q to close the tabpage
  vim.api.nvim_buf_set_keymap(gg_buf, "n", "q", "<cmd>tabclose<cr>", { noremap = true, silent = true, desc = "Close Git Dashboard Tab" })

  -- Map Ctrl-l to switch to the right split (Neogit)
  vim.api.nvim_buf_set_keymap(gg_buf, "n", "<C-l>", "<cmd>wincmd l<cr>", { noremap = true, silent = true, desc = "Focus Neogit split" })

  -- Create a vertical split for Neogit (default is right split)
  vim.cmd("vsplit")

  -- Open Neogit in the new split
  require("neogit").open({ kind = "replace", cwd = repo_path })

  -- Wait a split second for Neogit to load, then resize and map Ctrl-h
  vim.defer_fn(function()
    local screen_width = vim.o.columns
    local left_width = math.floor(screen_width * 0.40)

    if vim.api.nvim_win_is_valid(gg_win) then
      vim.api.nvim_win_set_width(gg_win, left_width)
    end

    -- Find Neogit buffer and add mappings
    local neogit_win = nil
    for _, w in ipairs(vim.api.nvim_list_wins()) do
      local b = vim.api.nvim_win_get_buf(w)
      if vim.bo[b].filetype == "NeogitStatus" then
        neogit_win = w
        break
      end
    end

    if neogit_win then
      local neogit_buf = vim.api.nvim_win_get_buf(neogit_win)
      
      -- Map Ctrl-h to switch back to GitGraph split
      vim.api.nvim_buf_set_keymap(neogit_buf, "n", "<C-h>", "<cmd>wincmd h<cr>", { noremap = true, silent = true, desc = "Focus GitGraph split" })

      -- Map q to close the tabpage
      vim.api.nvim_buf_set_keymap(neogit_buf, "n", "q", "<cmd>tabclose<cr>", { noremap = true, silent = true, desc = "Close Git Dashboard Tab" })
    end
  end, 50)
end

-- Toggle combined Git dashboard (GitGraph 40% and Neogit 60% in a new tab page)
function M.git_dashboard_toggle()
  -- Check if Git Dashboard tabpage already exists
  local dashboard_tab = nil
  for _, tab in ipairs(vim.api.nvim_list_tabpages()) do
    for _, win in ipairs(vim.api.nvim_tabpage_list_wins(tab)) do
      local buf = vim.api.nvim_win_get_buf(win)
      if vim.bo[buf].filetype == "NeogitStatus" then
        dashboard_tab = tab
        break
      end
    end
    if dashboard_tab then break end
  end

  if dashboard_tab then
    local current_tab = vim.api.nvim_get_current_tabpage()
    if current_tab == dashboard_tab then
      -- If we are in the dashboard tab, close it
      vim.cmd("tabclose")
    else
      -- If it exists but we are not in it, switch to it
      vim.api.nvim_set_current_tabpage(dashboard_tab)
    end
    return
  end

  -- Scan for git repositories in the project
  local repos = find_git_repos()
  if #repos == 0 then
    vim.notify("No git repositories found in " .. vim.fn.getcwd(), vim.log.levels.WARN)
    return
  end
  select_repo(repos, open_dashboard)
end

return M
