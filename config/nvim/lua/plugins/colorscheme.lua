return {
  -- Your github theme plugin spec
  {
    "projekt0n/github-nvim-theme",
    name = "github-theme",
    lazy = false,
    priority = 1000,
    config = function()
      require("github-theme").setup({
        -- options go here if needed
      })
      vim.cmd("colorscheme github_light")
    end,
  },
}
