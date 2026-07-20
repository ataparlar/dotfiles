return {
  "NeogitOrg/neogit",
  lazy = true,
  dependencies = {
    -- Only one of these is needed.
    "sindrets/diffview.nvim", -- optional

    -- For a custom log pager
    "m00qek/baleia.nvim", -- optional

    -- Only one of these is needed.
    "nvim-telescope/telescope.nvim", -- optional
  },
  cmd = "Neogit",
  opts = function()
    return {
      environment = {
        NVIM = vim.v.servername or vim.env.NVIM,
      },
      commit_editor = {
        kind = "auto",
      },
    }
  end,
  init = function()
    require("git").setup()
  end,
  keys = {
    {
      "<leader>gg",
      function()
        require("git").git_dashboard_toggle()
      end,
      desc = "Toggle Git Dashboard (Neogit & GitGraph)",
    },
  },
}
