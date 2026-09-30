#!/usr/bin/env python3
"""snap.py — aplikasi screenshot (Print -> drag kotak -> Ctrl+C ke clipboard).

Alur:
  1. Tekan Print Screen  -> layar beku (dim) + crosshair, drag untuk seleksi.
     Area terpilih langsung tampil terang (live preview), sisanya tetap gelap.
  2. Ctrl+C             -> crop area terpilih (drag aktif / hasil drag /
                           full screen bila belum ada seleksi), salin ke clipboard.
  3. Ctrl+S             -> simpan PNG ke ~/Pictures/Screenshots.
  4. Panah ←↑↓→          -> geser seleksi 1px (Shift = 10px).
     Ctrl+panah         -> ubah ukuran seleksi (Shift = langkah 10px).
  5. Esc / klik kanan   -> batal.

Desain: TIDAK pakai transparansi jendela. Setup i3 ini tidak punya compositor,
jadi attributes("-alpha") diabaikan X11 dan jendela jadi hitam pekat.
Sebagai gantinya: capture fullscreen dulu -> digelapkan via ffmpeg ->
ditampilkan sebagai background canvas (PhotoImage). Area seleksi "dibelah"
dengan salinan region dari gambar terang memakai Tcl `photo copy` (native,
~1ms) sehingga preview bisa live tanpa ffmpeg per-frame dan tanpa compositor.
Crop final SELALU dari file ASLI (belum digelapkan).

Keyboard grab global: focus_force tidak memindahkan X focus (Ctrl+C tidak
sampai), grab memaksa semua key event masuk ke overlay.

Butuh: python3 + tkinter, ffmpeg, xclip (xdotool untuk tes saja).
"""

import datetime
import os
import subprocess
import sys
import tkinter as tk

FULL_PATH = "/tmp/snap_full.png"   # capture fullscreen asli (sumber crop)
DIM_PATH = "/tmp/snap_dim.png"     # versi gelap (background overlay)
SEL_PATH = "/tmp/snap_sel.png"     # hasil crop (yang di-copy ke clipboard)
SAVE_DIR = os.path.expanduser("~/Pictures/Screenshots")
DEBUG_LOG = "/tmp/snap-debug.log"

HINT_BASE = ("Drag untuk seleksi  •  Ctrl+C salin  •  Ctrl+S simpan  •  "
             "←↑↓→ geser (Ctrl: ukuran)  •  Esc batal")


def log(msg):
    try:
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except OSError:
        pass


def sh(*args, **kwargs):
    return subprocess.run(args, capture_output=True, **kwargs)


def screen_size():
    r = tk.Tk()
    r.withdraw()
    w, h = r.winfo_screenwidth(), r.winfo_screenheight()
    r.destroy()
    return w, h


def capture_fullscreen(path, w, h):
    r = sh("ffmpeg", "-y", "-loglevel", "error",
           "-f", "x11grab", "-video_size", f"{w}x{h}", "-i", ":0",
           "-frames:v", "1", path)
    return r.returncode == 0 and os.path.exists(path) \
        and os.path.getsize(path) > 0


def make_dim(src, dst):
    """Gelapkan screenshot untuk background overlay (tanpa compositor)."""
    if os.path.exists(dst):
        os.remove(dst)
    # NOTE: sintaks "0.35:0.35:0.35" SALAH — itu menyetel rr:rg:rb
    # (R' = 0.35R+0.35G+0.35B, G/B utuh) sehingga pixel abu-abu tidak berubah.
    # Wajib pakai nama kanal: rr/gg/bb.
    r = sh("ffmpeg", "-y", "-loglevel", "error", "-i", src,
           "-vf", "colorchannelmixer=rr=0.35:gg=0.35:bb=0.35", dst)
    return r.returncode == 0 and os.path.exists(dst) \
        and os.path.getsize(dst) > 0


def crop(src, dst, x, y, w, h):
    if os.path.exists(dst):
        os.remove(dst)
    r = sh("ffmpeg", "-y", "-loglevel", "error", "-i", src,
           "-vf", f"crop={w}:{h}:{x}:{y}", "-frames:v", "1", dst)
    return r.returncode == 0 and os.path.exists(dst) \
        and os.path.getsize(dst) > 0


def copy_png_to_clipboard(png_path):
    """xclip -i jadi pemilik selection; dilepas agar awet setelah app keluar."""
    subprocess.Popen(
        ["xclip", "-selection", "clipboard", "-t", "image/png",
         "-i", png_path],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )


def normalize(x0, y0, x1, y1):
    """Kotak drag -> (x, y, w, h) non-negatif, di dalam layar asumsi pointer."""
    x, y = min(x0, x1), min(y0, y1)
    return x, y, abs(x1 - x0), abs(y1 - y0)


class SnapApp:
    def __init__(self, root, w, h, dim_path, full_path):
        self.root = root
        self.W, self.H = w, h
        self.start = None
        self.cur = None
        self.sel = None
        self.done = False
        self.busy = False          # cegah aksi ganda selama flash/quit
        self.quitting = False
        self.rect_id = None
        self.label_id = None
        self.label_bg = None
        self.preview_id = None
        self.preview_img = None
        self._last_prev = None

        root.overrideredirect(True)          # lewati WM -> mengambang di atas
        root.geometry(f"{w}x{h}+0+0")
        root.configure(background="black")
        try:
            root.attributes("-topmost", True)
        except Exception as e:
            log(f"topmost gagal: {e}")
        # NOTE: attributes("-alpha") TIDAK dipakai — tanpa compositor hasilnya
        # jendela hitam pekat (bug "blank hitam"). Dim lewat gambar, lihat make_dim.

        self.canvas = tk.Canvas(root, width=w, height=h,
                                background="black",
                                highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        # Latar: screenshot versi gelap (bukan transparansi jendela).
        self.bg_img = None
        try:
            self.bg_img = tk.PhotoImage(file=dim_path)
            self.canvas.create_image(0, 0, image=self.bg_img, anchor="nw")
            log(f"background dim dimuat: {dim_path}")
        except Exception as e:
            log(f"background dim gagal: {e}")

        # Gambar terang: sumber live preview (salinan region in-memory).
        self.full_img = None
        try:
            self.full_img = tk.PhotoImage(file=full_path)
            log(f"gambar terang dimuat: {full_path}")
        except Exception as e:
            log(f"gambar terang gagal: {e}")

        # Garis bantuan crosshair (dibuat paling awal -> selalu di bawah).
        self.gx = self.canvas.create_line(-10, -10, -10, h, fill="#b0b0b0",
                                          width=1, dash=(5, 9))
        self.gy = self.canvas.create_line(-10, -10, w, -10, fill="#b0b0b0",
                                          width=1, dash=(5, 9))

        # Hint bar (tag "hint", selalu di atas; lebar ikut lebar teks).
        self.hint_bg = self.canvas.create_rectangle(
            0, 0, 0, 0, fill="black", outline="", tags=("hint",))
        self.hint_id = self.canvas.create_text(
            w // 2, 28, fill="white", font=("monospace", 14, "bold"),
            tags=("hint",))
        self.set_hint(HINT_BASE)

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<ButtonPress-3>", lambda e: self.quit())
        root.bind_all("<Escape>", lambda e: self.quit())
        root.bind_all("<Control-c>", lambda e: self.do_copy())
        root.bind_all("<Control-C>", lambda e: self.do_copy())
        root.bind_all("<Control-s>", lambda e: self.do_save())
        root.bind_all("<Control-S>", lambda e: self.do_save())
        for keysym, dx, dy in (("<Up>", 0, -1), ("<Down>", 0, 1),
                               ("<Left>", -1, 0), ("<Right>", 1, 0)):
            root.bind_all(keysym,
                          lambda e, dx=dx, dy=dy: self.on_arrow(e, dx, dy))

        root.update_idletasks()
        root.update()
        root.lift()
        root.focus_force()
        # Keyboard grab global: focus_force ternyata tidak cukup (X focus
        # tetap di jendela lain -> Ctrl+C tidak sampai). Dengan grab ini
        # semua key event masuk ke overlay siapa pun yang pegang fokus.
        try:
            root.grab_set_global()
            log("keyboard grab global aktif")
        except Exception as e:
            log(f"grab global gagal: {e}")
        log(f"overlay {w}x{h} mapped={root.winfo_ismapped()}")
        root.after(200, root.lift)
        root.after(200, root.focus_force)

        def _regrab():
            try:
                root.grab_set_global()
            except Exception:
                pass
        root.after(200, _regrab)
        root.after(1000, _regrab)

    # ---- hint bar ----
    def set_hint(self, text, color="white"):
        self.canvas.itemconfig(self.hint_id, text=text, fill=color)
        bbox = self.canvas.bbox(self.hint_id)
        if bbox:
            pad = 16
            self.canvas.coords(self.hint_bg,
                               bbox[0] - pad, 6, bbox[2] + pad, 50)
        self.canvas.tag_raise("hint")

    def sel_hint(self):
        _, _, w, h = self.sel
        return (f"Terpilih {w} x {h}  •  Ctrl+C salin  •  Ctrl+S simpan  •  "
                "←↑↓→ geser (Ctrl: ukuran)  •  Esc batal")

    def warn(self, msg):
        """Pesan peringatan tanpa bell (aman untuk spam tombol)."""
        self.set_hint(msg, "#ffdd22")
        self.root.after(1500, lambda: self.set_hint(
            self.sel_hint() if self.done and self.sel else HINT_BASE))

    # ---- mouse ----
    def on_press(self, e):
        log(f"press {e.x},{e.y}")
        self.start = (e.x, e.y)
        self.cur = (e.x, e.y)
        self.done = False
        self.sel = None
        self._clear_sel()
        self.set_guides(e.x, e.y)
        self.set_hint(HINT_BASE)

    def on_drag(self, e):
        if self.start is None:
            return
        self.cur = (e.x, e.y)
        self.set_guides(e.x, e.y)
        x, y, w, h = normalize(self.start[0], self.start[1], e.x, e.y)
        self.draw_box(x, y, w, h)
        if w >= 5 and h >= 5:
            self.show_preview(x, y, w, h)
        else:
            self.clear_preview()

    def on_release(self, e):
        if self.start is None:
            return
        x, y, w, h = normalize(self.start[0], self.start[1], e.x, e.y)
        log(f"release {x},{y} {w}x{h}")
        self.start = None
        self.cur = None
        if w >= 5 and h >= 5:
            self.done = True
            self.sel = (x, y, w, h)
            self.draw_box(x, y, w, h)
            self.show_preview(x, y, w, h)
            self.set_hint(self.sel_hint())
        else:
            self.done = False
            self.sel = None
            self._clear_sel()
            self.set_hint(HINT_BASE)

    def set_guides(self, x, y):
        self.canvas.coords(self.gx, x, 0, x, self.H)
        self.canvas.coords(self.gy, 0, y, self.W, y)

    # ---- gambar seleksi + preview ----
    def draw_box(self, x, y, w, h):
        self._clear_rect()
        x1, y1 = x + w, y + h
        self.rect_id = self.canvas.create_rectangle(
            x, y, x1, y1, outline="#ff2222", width=3, tags=("sel",))
        # Label ukuran: dijaga tetap di dalam layar.
        lx = min(max(2, x), self.W - 140)
        ly = y1 + 10
        if ly + 28 > self.H:
            ly = y - 34
        ly = max(2, ly)
        self.label_bg = self.canvas.create_rectangle(
            lx - 6, ly - 4, lx + 132, ly + 22, fill="black", outline="",
            tags=("sel",))
        self.label_id = self.canvas.create_text(
            lx, ly, anchor="nw", text=f"{w} x {h}", fill="#ff4444",
            font=("monospace", 13, "bold"), tags=("sel",))
        self.canvas.tag_raise("sel")
        self.canvas.tag_raise("hint")

    def show_preview(self, x, y, w, h):
        """Salin region terang ke dalam kotak seleksi (Tcl photo copy, ~1ms)."""
        if self.full_img is None:
            return
        box = (x, y, w, h)
        if box == self._last_prev and self.preview_id is not None:
            return
        self.clear_preview()
        if w >= self.W and h >= self.H:
            img = self.full_img
        else:
            img = tk.PhotoImage(width=w, height=h)
            try:
                img.tk.call(img.name, "copy", self.full_img.name,
                            "-from", x, y, x + w, y + h,
                            "-to", 0, 0, w, h)
            except Exception as e:
                log(f"preview gagal: {e}")
                return
        self.preview_img = img
        self.preview_id = self.canvas.create_image(
            x, y, image=img, anchor="nw")
        self._last_prev = box
        self.canvas.tag_raise("sel")
        self.canvas.tag_raise("hint")

    def clear_preview(self):
        if self.preview_id is not None:
            self.canvas.delete(self.preview_id)
        self.preview_id = None
        self.preview_img = None
        self._last_prev = None

    def _clear_rect(self):
        for i in (self.rect_id, self.label_id, self.label_bg):
            if i:
                self.canvas.delete(i)
        self.rect_id = self.label_id = self.label_bg = None

    def _clear_sel(self):
        self._clear_rect()
        self.clear_preview()

    # ---- keyboard: panah ----
    def on_arrow(self, e, dx, dy):
        if not self.done or not self.sel:
            self.warn("Belum ada seleksi — drag dulu area dulu.")
            return "break"
        ctrl = bool(e.state & 0x0004)
        shift = bool(e.state & 0x0001)
        step = 10 if shift else 1
        x, y, w, h = self.sel
        if ctrl:  # ubah ukuran
            if dx:
                w += dx * step
            if dy:
                h += dy * step
            w = max(5, min(w, self.W - x))
            h = max(5, min(h, self.H - y))
        else:     # geser
            x = max(0, min(x + dx * step, self.W - w))
            y = max(0, min(y + dy * step, self.H - h))
        self.sel = (x, y, w, h)
        log(f"arrow {'ukuran' if ctrl else 'geser'} -> {x},{y} {w}x{h}")
        self.draw_box(x, y, w, h)
        self.show_preview(x, y, w, h)
        self.set_hint(self.sel_hint())
        return "break"

    # ---- aksi ----
    def effective_sel(self):
        """Seleksi untuk Ctrl+C/S: hasil drag, drag yang masih aktif, atau
        full screen. Mengembalikan (sel, full?)."""
        if self.done and self.sel:
            return self.sel, False
        if self.start and self.cur:
            x, y, w, h = normalize(self.start[0], self.start[1],
                                   self.cur[0], self.cur[1])
            if w >= 5 and h >= 5:
                return (x, y, w, h), False
        return (0, 0, self.W, self.H), True

    def bounds(self, sel):
        x, y, w, h = sel
        x = min(max(0, x), self.W - 1)
        y = min(max(0, y), self.H - 1)
        w = min(w, self.W - x)
        h = min(h, self.H - y)
        return x, y, w, h

    def do_copy(self):
        log("ctrl+c diterima")
        if self.busy:
            return
        sel, full = self.effective_sel()
        if full:
            log("tanpa seleksi -> full screen")
        self.busy = True
        x, y, w, h = self.bounds(sel)
        if not crop(FULL_PATH, SEL_PATH, x, y, w, h):
            self.busy = False
            self.flash("Gagal crop gambar.")
            return
        copy_png_to_clipboard(SEL_PATH)
        log(f"copied {w}x{h} ({os.path.getsize(SEL_PATH)}b) ke clipboard")
        if full:
            msg = f"Disalin layar penuh {w}x{h} — siap di-paste!"
        else:
            msg = f"Disalin {w}x{h} ke clipboard — siap di-paste!"
        self.flash(msg, ok=True, then_quit=True)

    def do_save(self):
        log("ctrl+s diterima")
        if self.busy:
            return
        sel, full = self.effective_sel()
        if full:
            log("tanpa seleksi -> simpan full screen")
        self.busy = True
        os.makedirs(SAVE_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        x, y, w, h = self.bounds(sel)
        dst = os.path.join(SAVE_DIR, f"snap_{ts}_{w}x{h}.png")
        if not crop(FULL_PATH, dst, x, y, w, h):
            self.busy = False
            self.flash("Gagal menyimpan gambar.")
            return
        log(f"saved {dst}")
        self.flash(f"Tersimpan: {dst}", ok=True, then_quit=True)

    def flash(self, msg, ok=False, then_quit=False):
        color = "#22ff66" if ok else "#ffdd22"
        self.set_hint(msg, color)
        try:
            self.root.bell()
        except Exception:
            pass
        if then_quit:
            self.busy = True
            self.root.after(900, self.quit)

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        try:
            self.root.grab_release()
        except Exception:
            pass
        self.root.destroy()


def main():
    if os.path.exists(DEBUG_LOG):
        os.remove(DEBUG_LOG)
    log("snap mulai")
    w, h = screen_size()
    log(f"screen {w}x{h}")
    if not capture_fullscreen(FULL_PATH, w, h):
        print("Gagal capture layar (ffmpeg x11grab).", file=sys.stderr)
        return 1
    log(f"captured {os.path.getsize(FULL_PATH)} bytes -> {FULL_PATH}")
    if not make_dim(FULL_PATH, DIM_PATH):
        log("gagal buat versi dim, fallback background hitam")
    root = tk.Tk()
    SnapApp(root, w, h, DIM_PATH, FULL_PATH)
    root.mainloop()
    log("snap keluar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
