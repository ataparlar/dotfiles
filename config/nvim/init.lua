-- bootstrap lazy.nvim, LazyVim and your plugins
require("config.lazy")

-- Configure a silent Wayland clipboard provider to suppress wl-copy connection errors
if vim.fn.executable("wl-copy") == 1 then
  vim.g.clipboard = {
    name = "wl-clipboard-silent",
    copy = {
      ["+"] = "wl-copy --type text/plain 2>/dev/null",
      ["*"] = "wl-copy --type text/plain --primary 2>/dev/null",
    },
    paste = {
      ["+"] = "wl-paste --no-newline 2>/dev/null",
      ["*"] = "wl-paste --no-newline --primary 2>/dev/null",
    },
    cache_enabled = true,
  }
  vim.opt.clipboard = "unnamedplus"
else
  vim.opt.clipboard = ""
end
