return {

  -- Configure clangd and add custom keymaps
  {
    "neovim/nvim-lspconfig",
    opts = {
      servers = {
        clangd = {
          cmd = {
            "clangd",
            "--background-index",
            "--clang-tidy",
            "--header-insertion=iwyu",
            "--completion-style=detailed",
            "--function-arg-placeholders=0", -- Fix invalid flag warning
            "--fallback-style=llvm",
          },
          keys = {
            { "<leader>ch", "<cmd>ClangdSwitchSourceHeader<cr>", desc = "Switch Source/Header" },
          },
        },
      },
    },
  },
}
