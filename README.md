# snap — aplikasi screenshot (Print -> drag kotak -> Ctrl+C ke clipboard)

Aplikasi screenshot minimal untuk Linux X11 + i3, dibuat karena Flameshot
tidak stabil di setup ini (overlay kadang tidak muncul / instance tray balapan).

## Cara pakai

1. Tekan **Print Screen** -> layar meredup, kursor jadi crosshair.
2. **Drag mouse** untuk membuat kotak seleksi (muncul ukuran `WxH`).
3. **Ctrl+C** -> area terpilih disalin ke clipboard sebagai PNG, siap di-paste ke mana saja.
4. **Ctrl+S** -> area terpilih disimpan ke `~/Pictures/Screenshots/snap_YYYYMMDD_HHMMSS.png`.
5. **Esc / klik kanan** -> batal.

## Instalasi

Butuh: `python3 + tkinter`, `ffmpeg`, `xclip` (semua sudah ada di PC ini).

```sh
chmod +x snap-print
ln -sf /home/mocharfian/ai/screenshoot/snap-print ~/.local/bin/snap-print
```

Tambahkan ke `~/.config/i3/config` (ganti binding Print yang lama):

```
bindsym Print exec --no-startup-id ~/.local/bin/snap-print
```

Reload i3 (`Mod+Shift+r`) lalu tekan Print.

## Cara kerja

- `snap.py` capture fullscreen via `ffmpeg x11grab` **sebelum** overlay tampil,
  lalu menampilkan versi gelap hasil `ffmpeg colorchannelmixer` sebagai
  background canvas (PhotoImage).
  **Bukan transparansi jendela** — setup ini tidak punya compositor, jadi
  `attributes("-alpha")` diabaikan X11 dan jendela jadi hitam pekat.
- Overlay pakai keyboard **grab global** (`grab_set_global`) supaya Ctrl+C /
  Ctrl+S / Esc tetap diterima walau X focus ada di jendela lain.
- Koordinat drag dipakai untuk `crop` via ffmpeg **dari file asli** (belum
  digelapkan), hasilnya diserahkan ke clipboard X11 (`CLIPBOARD`, `image/png`)
  lewat `xclip -i` yang dilepas sebagai proses background agar clipboard awet
  setelah app keluar.
- Tanpa Pillow, tanpa daemon tray — sekali jalan, sekali pakai.

## File sementara

- `/tmp/snap_full.png` — capture fullscreen terakhir (sumber crop)
- `/tmp/snap_dim.png` — versi gelap (background overlay)
- `/tmp/snap_sel.png` — hasil crop terakhir (yang masuk clipboard)
- `/tmp/snap-debug.log` — log debug (ada timestamp)
