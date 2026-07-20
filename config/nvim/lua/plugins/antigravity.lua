return {
  {
    "antigravity",
    dir = vim.fn.stdpath("config"),
    opts = {
      cmd = "agy",
      width = 0.35,
      height = 0.8,
      border = "rounded",
      layout = "split",
    },
    init = function()
      -- Register keymap group description in which-key during startup (so it shows immediately)
      vim.schedule(function()
        local wk_ok, wk = pcall(require, "which-key")
        if wk_ok then
          if wk.add then
            wk.add({
              { "<leader>a", group = "antigravity", icon = "󰚩" },
              { "<leader>a", group = "antigravity", mode = "v", icon = "󰚩" },
            })
          else
            wk.register({
              ["<leader>a"] = { name = "+antigravity" }
            }, { mode = "n" })
            wk.register({
              ["<leader>a"] = { name = "+antigravity" }
            }, { mode = "v" })
          end
        end
      end)
    end,
    config = function(_, opts)
      require("antigravity").setup(opts)

      -- Register user commands
      vim.api.nvim_create_user_command("AntigravityToggle", function()
        require("antigravity").toggle()
      end, {})

      vim.api.nvim_create_user_command("AntigravityContinue", function()
        require("antigravity").toggle("-c")
      end, {})

      vim.api.nvim_create_user_command("AntigravityNew", function()
        require("antigravity").new_conversation()
      end, {})

      vim.api.nvim_create_user_command("AntigravitySelect", function()
        require("antigravity").select_conversation()
      end, {})

      -- Add short aliases
      vim.api.nvim_create_user_command("AgyToggle", function()
        require("antigravity").toggle()
      end, {})

      vim.api.nvim_create_user_command("AgyContinue", function()
        require("antigravity").toggle("-c")
      end, {})

      vim.api.nvim_create_user_command("AgyNew", function()
        require("antigravity").new_conversation()
      end, {})

      vim.api.nvim_create_user_command("AgySelect", function()
        require("antigravity").select_conversation()
      end, {})
    end,
    keys = {
      -- Normal mode keymaps
      { "<leader>at", "<cmd>AntigravityToggle<cr>", desc = "Toggle Antigravity Agent" },
      { "<leader>ac", "<cmd>AntigravityContinue<cr>", desc = "Continue Antigravity Agent Session" },
      { "<leader>an", "<cmd>AntigravityNew<cr>", desc = "New Antigravity Conversation" },
      { "<leader>as", "<cmd>AntigravitySelect<cr>", desc = "Select & Resume Past Conversation" },
      -- Send current visual selection to interactive terminal
      {
        "<leader>as",
        function()
          local selection = require("antigravity").get_visual_selection()
          require("antigravity").send(selection)
        end,
        mode = "v",
        desc = "Send selection to Antigravity Agent",
      },
    },
  }
}
