-- Fix Neogit / Neovim RPC server in Docker containers
local runtime_dir = vim.fn.stdpath("state")
if runtime_dir == "" or not runtime_dir then
  runtime_dir = "/tmp"
end
vim.env.XDG_RUNTIME_DIR = runtime_dir

if vim.v.servername == nil or vim.v.servername == "" then
  local pipe_path = string.format("%s/nvim_%d.pipe", runtime_dir, vim.fn.getpid())
  local ok, server = pcall(vim.fn.serverstart, pipe_path)
  if ok and server and server ~= "" then
    vim.env.NVIM = server
  end
end

if vim.v.servername and vim.v.servername ~= "" then
  vim.env.NVIM = vim.v.servername
end

-- bootstrap lazy.nvim, LazyVim and your plugins
require("config.lazy")


-- Enable system clipboard integration if a clipboard provider is available
if vim.fn.has("clipboard") == 1 then
  vim.opt.clipboard = "unnamedplus"
end

