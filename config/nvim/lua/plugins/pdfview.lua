return {
  "basola21/PDFview",
  lazy = false,
  dependencies = { "nvim-telescope/telescope.nvim" },
  keys = {
    { "<leader>po", "<cmd>lua require('pdfview').open()<cr>", desc = "Open PDF with Telescope" },
    { "<leader>pn", "<cmd>lua require('pdfview.renderer').next_page()<cr>", desc = "Next PDF Page" },
    { "<leader>pp", "<cmd>lua require('pdfview.renderer').prev_page()<cr>", desc = "Previous PDF Page" },
  },
  config = function()
    -- Automatically open PDF files using PDFview when attempting to read a .pdf buffer
    vim.api.nvim_create_autocmd("BufReadPost", {
      pattern = "*.pdf",
      callback = function()
        local file_path = vim.api.nvim_buf_get_name(0)
        if file_path and file_path ~= "" then
          require("pdfview").open(file_path)
        end
      end,
    })

    -- Register which-key group description for PDF
    local wk_ok, wk = pcall(require, "which-key")
    if wk_ok then
      if wk.add then
        wk.add({
          { "<leader>p", group = "PDF", icon = "󰈙" },
        })
      else
        wk.register({
          ["<leader>p"] = { name = "+PDF" }
        }, { mode = "n" })
      end
    end
  end,
}
