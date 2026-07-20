-- bootstrap lazy.nvim, LazyVim and your plugins
require("config.lazy")

-- Enable system clipboard integration if a clipboard provider is available
if vim.fn.has("clipboard") == 1 then
  vim.opt.clipboard = "unnamedplus"
end

