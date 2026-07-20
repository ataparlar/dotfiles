local M = {}

M.state = {
  term_buf = nil,
  term_win = nil,
  term_chan = nil,
}

M.config = {
  cmd = "agy",
  width = 0.35,
  height = 0.8,
  border = "rounded",
  layout = "split",
}

function M.setup(opts)
  M.config = vim.tbl_deep_extend("force", M.config, opts or {})
end

local function get_float_opts()
  local screen_width = vim.o.columns
  local screen_height = vim.o.lines
  local width = math.floor(screen_width * M.config.width)
  local height = math.floor(screen_height * M.config.height)
  local row = math.floor((screen_height - height) / 2) - 1
  local col = math.floor((screen_width - width) / 2)

  local win_opts = {
    relative = "editor",
    width = width,
    height = height,
    row = row,
    col = col,
    style = "minimal",
    border = M.config.border,
  }

  -- If Neovim version supports title, add title
  if vim.fn.has("nvim-0.9.0") == 1 then
    win_opts.title = " Antigravity Agent "
    win_opts.title_pos = "center"
  end

  return win_opts
end

function M.toggle(args)
  args = args or ""

  -- If terminal window is open, close/hide it
  if M.state.term_win and vim.api.nvim_win_is_valid(M.state.term_win) then
    vim.api.nvim_win_close(M.state.term_win, true)
    M.state.term_win = nil
    return
  end

  local is_new_buf = false
  -- Create terminal buffer if it doesn't exist or is invalid
  if not M.state.term_buf or not vim.api.nvim_buf_is_valid(M.state.term_buf) then
    M.state.term_buf = vim.api.nvim_create_buf(false, true) -- no file, scratch
    is_new_buf = true
  end

  if M.config.layout == "float" then
    -- Open floating window
    local win_opts = get_float_opts()
    M.state.term_win = vim.api.nvim_open_win(M.state.term_buf, true, win_opts)
    vim.wo[M.state.term_win].winhl = "Normal:Normal,FloatBorder:FloatBorder"
  else
    -- Open in a vertical split on the right side
    vim.cmd("botright vsplit")
    M.state.term_win = vim.api.nvim_get_current_win()
    vim.api.nvim_win_set_buf(M.state.term_win, M.state.term_buf)

    -- Style the sidebar window nicely
    vim.wo[M.state.term_win].number = false
    vim.wo[M.state.term_win].relativenumber = false
    vim.wo[M.state.term_win].signcolumn = "no"
    vim.wo[M.state.term_win].foldcolumn = "0"

    -- Set sidebar width
    local width = math.floor(vim.o.columns * (M.config.width < 1 and M.config.width or 0.35))
    if width > 10 then
      vim.api.nvim_win_set_width(M.state.term_win, width)
    end
  end

  if is_new_buf then
    -- Run agy in terminal buffer
    local full_cmd = M.config.cmd
    if args ~= "" then
      full_cmd = full_cmd .. " " .. args
    end

    -- termopen starts terminal and sets b:terminal_job_id
    M.state.term_chan = vim.fn.termopen(full_cmd, {
      on_exit = function()
        -- Clean up state when agent exits
        M.state.term_buf = nil
        M.state.term_chan = nil
        if M.state.term_win and vim.api.nvim_win_is_valid(M.state.term_win) then
          vim.api.nvim_win_close(M.state.term_win, true)
          M.state.term_win = nil
        end
      end
    })

    -- Add terminal mappings for this buffer
    local buf = M.state.term_buf
    -- Easy close: Ctrl+g toggles it
    vim.keymap.set("t", "<C-g>", function()
      M.toggle()
    end, { buffer = buf, desc = "Toggle Antigravity Agent Window" })

    -- In normal mode, q or Esc closes it
    vim.keymap.set("n", "q", function()
      M.toggle()
    end, { buffer = buf, desc = "Close Antigravity Agent Window" })

    vim.keymap.set("n", "<Esc>", function()
      M.toggle()
    end, { buffer = buf, desc = "Close Antigravity Agent Window" })

    -- In terminal mode, Esc escapes to normal mode
    vim.keymap.set("t", "<Esc>", "<C-\\><C-n>", { buffer = buf, desc = "Escape Terminal Mode" })
  end

  -- Always start in insert mode
  vim.cmd("startinsert")
end

-- Force start a new conversation by deleting the active buffer if it exists
function M.new_conversation()
  if M.state.term_buf and vim.api.nvim_buf_is_valid(M.state.term_buf) then
    pcall(vim.api.nvim_buf_delete, M.state.term_buf, { force = true })
  end
  M.toggle()
end

-- Get current visual selection in a robust way
function M.get_visual_selection()
  local old_reg = vim.fn.getreg("z")
  local old_regtype = vim.fn.getregtype("z")
  
  vim.cmd('normal! "zy')
  local selection = vim.fn.getreg("z")
  
  vim.fn.setreg("z", old_reg, old_regtype)
  return selection
end

-- Send prompt/selection directly to the running/interactive terminal
function M.send(text)
  if not text or text == "" then return end

  -- If buffer/channel is already running, send text and focus window
  if M.state.term_chan and M.state.term_buf and vim.api.nvim_buf_is_valid(M.state.term_buf) then
    vim.api.nvim_chan_send(M.state.term_chan, text .. "\n")
    -- If window is not open, open it
    if not M.state.term_win or not vim.api.nvim_win_is_valid(M.state.term_win) then
      M.toggle()
    end
  else
    -- Otherwise start it and paste
    M.toggle("-c") -- Default to continue previous conversation
    vim.defer_fn(function()
      if M.state.term_chan then
        vim.api.nvim_chan_send(M.state.term_chan, text .. "\n")
      end
    end, 300)
  end
end

-- Run a non-interactive prompt and stream results to a split pane
function M.run_prompt_stream(prompt)
  if not prompt or prompt == "" then
    prompt = vim.fn.input("Prompt Antigravity: ")
    if prompt == "" then return end
  end

  -- Create split window
  vim.cmd("vsplit")
  local win = vim.api.nvim_get_current_win()
  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_win_set_buf(win, buf)

  -- Set buffer options
  vim.api.nvim_buf_set_name(buf, "Antigravity Response")
  vim.bo[buf].filetype = "markdown"
  vim.bo[buf].buftype = "nofile"
  vim.bo[buf].bufhidden = "wipe"
  vim.bo[buf].swapfile = false

  -- Set lines with prompt title and loading status
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, {
    "# Antigravity Response",
    "",
    "**Prompt:** " .. prompt,
    "",
    "> Running agent...",
  })

  local cmd = { M.config.cmd, "--print", prompt }

  local last_line_idx = 5

  local job_id = vim.fn.jobstart(cmd, {
    stdout_buffered = false,
    on_stdout = function(_, data, _)
      if not data then return end
      vim.schedule(function()
        if not vim.api.nvim_buf_is_valid(buf) then return end

        -- Remove the initial running indicator when stdout arrives
        local current_lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
        if current_lines[5] == "> Running agent..." then
          vim.api.nvim_buf_set_lines(buf, 4, 5, false, {})
          last_line_idx = 4
        end

        local current_last_line = vim.api.nvim_buf_get_lines(buf, last_line_idx - 1, last_line_idx, false)[1] or ""
        local new_lines = {}

        for i, val in ipairs(data) do
          if i == 1 then
            new_lines[1] = current_last_line .. val
          else
            table.insert(new_lines, val)
          end
        end

        vim.api.nvim_buf_set_lines(buf, last_line_idx - 1, last_line_idx, false, new_lines)
        last_line_idx = vim.api.nvim_buf_line_count(buf)

        -- Scroll to bottom of window
        pcall(vim.api.nvim_win_set_cursor, win, { last_line_idx, 0 })
      end)
    end,
    on_stderr = function(_, _, _)
      -- Ignore or handle errors
    end,
    on_exit = function(_, exit_code, _)
      vim.schedule(function()
        if vim.api.nvim_buf_is_valid(buf) then
          -- If there was a failure exit code, show it
          if exit_code ~= 0 then
            local current_lines = vim.api.nvim_buf_get_lines(buf, 0, -1, false)
            if current_lines[5] == "> Running agent..." then
              vim.api.nvim_buf_set_lines(buf, 4, 5, false, { "> Failed to run agent." })
            else
              local total_lines = vim.api.nvim_buf_line_count(buf)
              vim.api.nvim_buf_set_lines(buf, total_lines, total_lines, false, {
                "",
                "> [!ERROR] Agent exited with code " .. exit_code
              })
            end
          end
        end
      end)
    end
  })
  if job_id <= 0 then
    vim.api.nvim_err_writeln("Failed to start Antigravity agent process.")
  end
end

-- Select from past conversations associated with the current workspace and resume it
function M.select_conversation()
  -- Define the python script content to query database files
  local python_code = [[
import os, sqlite3, re, datetime, json, sys

conversations_dir = "/home/devv/.gemini/antigravity-cli/conversations"
project_path = sys.argv[1]

def get_session_preview(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT step_payload, metadata FROM steps ORDER BY idx ASC;")
        rows = cursor.fetchall()
        for row in rows:
            for val in row:
                if not val: continue
                text = val.decode('utf-8', errors='ignore')
                matches = re.findall(r'[\x20-\x7E\n\t]{15,}', text)
                for m in matches:
                    m_clean = m.strip().replace('\n', ' ').replace('\t', ' ')
                    m_clean = re.sub(r'\s+', ' ', m_clean)
                    if len(m_clean.split()) >= 4:
                        if not m_clean.startswith('{') and not m_clean.startswith('/') and not m_clean.startswith("b'") and 'sessionID' not in m_clean:
                            if not m_clean.startswith('import ') and not m_clean.startswith('local '):
                                return m_clean[:65]
        conn.close()
    except:
        pass
    return "No preview available"

results = []
if os.path.exists(conversations_dir):
    for f in os.listdir(conversations_dir):
        if not f.endswith(".db"): continue
        db_path = os.path.join(conversations_dir, f)
        try:
            with open(db_path, 'rb') as db_file:
                content = db_file.read()
            if project_path.encode('utf-8') in content:
                mtime = os.path.getmtime(db_path)
                dt = datetime.datetime.fromtimestamp(mtime)
                date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                preview = get_session_preview(db_path)
                results.append({
                    "id": f[:-3],
                    "date": date_str,
                    "preview": preview,
                    "timestamp": mtime
                })
        except:
            pass

results.sort(key=lambda x: x["timestamp"], reverse=True)
print(json.dumps(results))
]]

  -- Get current working directory
  local cwd = vim.fn.getcwd()
  
  -- Run the python script
  local cmd = { "python3", "-c", python_code, cwd }
  
  vim.fn.jobstart(cmd, {
    stdout_buffered = true,
    on_stdout = function(_, data, _)
      if not data or #data == 0 or data[1] == "" then
        vim.notify("No past Antigravity conversations found for this project.", vim.log.levels.INFO)
        return
      end
      
      -- Parse JSON
      local raw_json = table.concat(data, "")
      local ok, sessions = pcall(vim.json.decode, raw_json)
      if not ok or not sessions or #sessions == 0 then
        vim.notify("No past Antigravity conversations found for this project.", vim.log.levels.INFO)
        return
      end
      
      -- Build options for select
      local options = {}
      local session_map = {}
      for _, s in ipairs(sessions) do
        local label = string.format("[%s] %s (%s...)", s.date, s.preview, s.id:sub(1, 8))
        table.insert(options, label)
        session_map[label] = s
      end
      
      -- Show selection dialog
      vim.ui.select(options, {
        prompt = "Select Antigravity Conversation to resume:",
        format_item = function(item) return item end,
      }, function(choice)
        if choice then
          local selected = session_map[choice]
          if selected then
            -- Launch terminal with the selected conversation id
            M.toggle("--conversation " .. selected.id)
          end
        end
      end)
    end,
    on_stderr = function(_, data, _)
      -- Log errors if any
      if data and #data > 0 and data[1] ~= "" then
        local err = table.concat(data, "\n")
        if err:find("Traceback") then
          vim.notify("Error scanning conversations: " .. err, vim.log.levels.ERROR)
        end
      end
    end
  })
end

return M

