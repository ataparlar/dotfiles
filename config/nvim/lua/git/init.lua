local M = {}

M.config = {
  border = "rounded",
}

function M.setup(opts)
  M.config = vim.tbl_deep_extend("force", M.config, opts or {})
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

  -- Load plugins
  pcall(function()
    require("lazy").load({ plugins = { "gitgraph.nvim", "neogit" } })
  end)

  -- Create a new tab page
  vim.cmd("tabnew")
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
  require("neogit").open({ kind = "replace" })

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

return M
