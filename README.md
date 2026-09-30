# snap — aplikasi screenshot (Print -> drag kotak -> Ctrl+C ke clipboard)

Aplikasi screenshot minimal untuk Linux X11 + i3, dibuat karena Flameshot
tidak stabil di setup ini (overlay kadang tidak muncul / instance tray balapan).

## Cara pakai

1. Tekan **Print Screen** -> layar meredup, kursor jadi crosshair, muncul
   garis bantuan (dashed) yang mengikuti kursor.
2. **Drag mouse** untuk membuat kotak seleksi. Area di dalam kotak langsung
   tampil **terang (live preview)**, sisanya tetap gelap; muncul label ukuran
   `W x H`.
3. **Ctrl+C** -> area terpilih disalin ke clipboard sebagai PNG, siap di-paste
   ke mana saja. Kalau belum ada seleksi -> seluruh layar.
4. **Ctrl+S** -> simpan ke
   `~/Pictures/Screenshots/snap_YYYYMMDD_HHMMSS_WxH.png`
   (tanpa seleksi = seluruh layar).
5. **Panah ←↑↓→** -> geser seleksi 1 px (**Shift** = 10 px).
   **Ctrl+panah** -> ubah ukuran seleksi (kiri/kanan = lebar,
   atas/bawah = tinggi; Shift = langkah 10 px).
6. **Esc / klik kanan** -> batal.

Tekan panah sebelum ada seleksi -> muncul peringatan kuning di hint bar.

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

- `snap.py` capture fullscreen via `ffmpeg x11grab` **sebelum** overlay tampil:
  - `/tmp/snap_full.png` — asli (sumber preview & crop),
  - `/tmp/snap_dim.png` — versi gelap hasil
    `colorchannelmixer=rr=0.35:gg=0.35:bb=0.35` (wajib pakai nama kanal;
    `0.35:0.35:0.35` positional menyetel `rr:rg:rb` dan tidak menggelapkan),
    dipakai sebagai background canvas.
  **Bukan transparansi jendela** — setup ini tidak punya compositor, jadi
  `attributes("-alpha")` diabaikan X11 dan jendela jadi hitam pekat.
- Live preview: region dari gambar terang disalin ke dalam kotak seleksi
  memakai Tcl `photo copy` native (~1 ms) — tanpa ffmpeg per-frame dan tanpa
  Pillow. Crop final tetap dari file asli lewat ffmpeg.
- Overlay pakai keyboard **grab global** (`grab_set_global`) supaya Ctrl+C /
  Ctrl+S / panah / Esc tetap diterima walau X focus ada di jendela lain
  (`focus_force()` ternyata tidak memindahkan X focus).
- Hasilnya diserahkan ke clipboard X11 (`CLIPBOARD`, `image/png`) lewat
  `xclip -i` yang dilepas sebagai proses background agar clipboard awet
  setelah app keluar.
- Tanpa daemon tray — sekali jalan, sekali pakai.

## File sementara

- `/tmp/snap_full.png` — capture fullscreen terakhir (sumber crop/preview)
- `/tmp/snap_dim.png` — versi gelap (background overlay)
- `/tmp/snap_sel.png` — hasil crop terakhir (yang masuk clipboard)
- `/tmp/snap-debug.log` — log debug (ada timestamp)
