return {
  "lervag/vimtex",
  lazy = false, -- we don't want to lazy load VimTeX
  -- tag = "v2.15", -- uncomment to pin to a specific release
  init = function()
    -- VimTeX configuration goes here, e.g.
    vim.g.vimtex_view_method = "zathura"
  end,
  config = function()
    -- Create an autocmd to bind keys specifically for LaTeX files
    vim.api.nvim_create_autocmd("FileType", {
      pattern = "tex",
      callback = function(event)
        local opts = { buffer = event.buf, silent = true }

        -- Set up keymaps under <leader>v
        vim.keymap.set("n", "<leader>vc", "<cmd>VimtexCompile<cr>", vim.tbl_extend("force", opts, { desc = "Compile / Toggle continuous build" }))
        vim.keymap.set("n", "<leader>vv", "<cmd>VimtexView<cr>", vim.tbl_extend("force", opts, { desc = "View PDF" }))
        vim.keymap.set("n", "<leader>vs", "<cmd>VimtexStop<cr>", vim.tbl_extend("force", opts, { desc = "Stop compilation" }))
        vim.keymap.set("n", "<leader>vt", "<cmd>VimtexTocToggle<cr>", vim.tbl_extend("force", opts, { desc = "Toggle Table of Contents" }))
        vim.keymap.set("n", "<leader>vi", "<cmd>VimtexInfo<cr>", vim.tbl_extend("force", opts, { desc = "VimTeX Info" }))
        vim.keymap.set("n", "<leader>ve", "<cmd>VimtexErrors<cr>", vim.tbl_extend("force", opts, { desc = "Show compilation errors" }))
        vim.keymap.set("n", "<leader>vx", "<cmd>VimtexClean<cr>", vim.tbl_extend("force", opts, { desc = "Clean auxiliary files" }))
        vim.keymap.set("n", "<leader>vX", "<cmd>VimtexCleanAll<cr>", vim.tbl_extend("force", opts, { desc = "Clean all files (incl. PDF)" }))
        vim.keymap.set("n", "<leader>vm", "<cmd>VimtexStatus<cr>", vim.tbl_extend("force", opts, { desc = "Show VimTeX Status" }))
        vim.keymap.set("n", "<leader>vr", "<cmd>VimtexReload<cr>", vim.tbl_extend("force", opts, { desc = "Reload VimTeX State" }))

        -- Register buffer-local which-key descriptions
        local wk_ok, wk = pcall(require, "which-key")
        if wk_ok then
          if wk.add then
            wk.add({
              { "<leader>v", group = "VimTeX", icon = "󰏆", buffer = event.buf },
            })
          else
            wk.register({
              ["<leader>v"] = { name = "+VimTeX" }
            }, { mode = "n", buffer = event.buf })
          end
        end
      end,
    })
  end,
}
