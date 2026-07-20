set clipboard=unnamedplus
if !has("clipboard") && executable("wl-copy") && executable("wl-paste")
  augroup WaylandClipboard
    autocmd!
    autocmd TextYankPost * if v:event.operator ==# "y" | call system("wl-copy", @") | endif
  augroup END
  nnoremap p :let @" = system("wl-paste --no-newline")<CR>p
  nnoremap P :let @" = system("wl-paste --no-newline")<CR>P
  vnoremap p :<C-u>let @" = system("wl-paste --no-newline")<CR>gv"0p
  endif
