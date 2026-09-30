#!/usr/bin/env python3
"""snap.py — aplikasi screenshot (Print -> drag kotak -> Ctrl+C ke clipboard).

Alur:
  1. Tekan Print Screen  -> layar membeku (dim) + crosshair, drag mouse buat kotak.
  2. Ctrl+C             -> crop area terpilih dari capture, salin PNG ke clipboard.
  3. Ctrl+S             -> simpan area terpilih sebagai file PNG.
  4. Esc / klik kanan   -> batal.

Desain: TIDAK pakai transparansi jendela. Setup i3 ini tidak punya compositor,
jadi attributes("-alpha") diabaikan X11 dan jendela jadi hitam pekat.
Sebagai gantinya: capture fullscreen dulu -> digelapkan via ffmpeg ->
ditampilkan sebagai background canvas (PhotoImage). Efeknya sama seperti dim
flameshot, tanpa butuh compositor. Crop selalu dari file ASLI (belum digelapkan).

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
    r = sh("ffmpeg", "-y", "-loglevel", "error", "-i", src,
           "-vf", "colorchannelmixer=0.35:0.35:0.35", dst)
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


class SnapApp:
    def __init__(self, root, w, h, dim_path):
        self.root = root
        self.W, self.H = w, h
        self.start = None
        self.rect_id = None
        self.label_id = None
        self.label_bg = None
        self.done = False
        self.sel = None

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

        # Background: screenshot versi gelap (bukan transparansi jendela).
        self.bg_img = None
        try:
            self.bg_img = tk.PhotoImage(file=dim_path)
            self.canvas.create_image(0, 0, image=self.bg_img, anchor="nw")
            log(f"background dim dimuat: {dim_path}")
        except Exception as e:
            log(f"background dim gagal: {e}")

        # Rectangle dulu (jadi latar), teks di atasnya supaya tidak tertutup.
        self.canvas.create_rectangle(
            w // 2 - 340, 8, w // 2 + 340, 48, fill="black", outline="")
        hint = ("Drag untuk seleksi  •  Ctrl+C salin  •  "
                "Ctrl+S simpan  •  Esc batal")
        self.hint_id = self.canvas.create_text(
            w // 2, 28, text=hint, fill="white",
            font=("monospace", 14, "bold"))

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<ButtonPress-3>", lambda e: self.quit())
        root.bind_all("<Escape>", lambda e: self.quit())
        root.bind_all("<Control-c>", lambda e: self.do_copy())
        root.bind_all("<Control-C>", lambda e: self.do_copy())
        root.bind_all("<Control-s>", lambda e: self.do_save())
        root.bind_all("<Control-S>", lambda e: self.do_save())

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

    # ---- mouse ----
    def on_press(self, e):
        log(f"press {e.x},{e.y}")
        self.start = (e.x, e.y)
        self.done = False
        self.sel = None
        self._clear_rect()

    def on_drag(self, e):
        if self.start is None:
            return
        x0, y0 = self.start
        self._clear_rect()
        self.rect_id = self.canvas.create_rectangle(
            x0, y0, e.x, e.y, outline="#ff2222", width=3)
        ww, hh = abs(e.x - x0), abs(e.y - y0)
        lx, ly = min(x0, e.x), max(y0, e.y) + 10
        self.label_bg = self.canvas.create_rectangle(
            lx - 4, ly - 4, lx + 130, ly + 22, fill="black", outline="")
        self.label_id = self.canvas.create_text(
            lx, ly, anchor="nw", text=f"{ww} x {hh}", fill="#ff4444",
            font=("monospace", 13, "bold"))

    def on_release(self, e):
        if self.start is None:
            return
        x0, y0 = self.start
        x1, y1 = e.x, e.y
        x, y = max(0, min(x0, x1)), max(0, min(y0, y1))
        w, h = abs(x1 - x0), abs(y1 - y0)
        log(f"release {x},{y} {w}x{h}")
        self.done = (w >= 5 and h >= 5)
        self.sel = (x, y, w, h) if self.done else None

    def _clear_rect(self):
        for i in (self.rect_id, self.label_id, self.label_bg):
            if i:
                self.canvas.delete(i)
        self.rect_id = self.label_id = self.label_bg = None

    # ---- aksi ----
    def bounds(self):
        x, y, w, h = self.sel
        x = min(max(0, x), self.W - 1)
        y = min(max(0, y), self.H - 1)
        w = min(w, self.W - x)
        h = min(h, self.H - y)
        return x, y, w, h

    def do_copy(self):
        log("ctrl+c diterima")
        if not self.done:
            self.flash("Drag dulu area yang mau disalin!")
            return
        x, y, w, h = self.bounds()
        if not crop(FULL_PATH, SEL_PATH, x, y, w, h):
            self.flash("Gagal crop gambar.")
            return
        copy_png_to_clipboard(SEL_PATH)
        log(f"copied {w}x{h} ({os.path.getsize(SEL_PATH)}b) ke clipboard")
        self.flash(f"Disalin {w}x{h} ke clipboard — siap di-paste!",
                   ok=True, then_quit=True)

    def do_save(self):
        log("ctrl+s diterima")
        if not self.done:
            self.flash("Drag dulu area yang mau disimpan!")
            return
        os.makedirs(SAVE_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(SAVE_DIR, f"snap_{ts}.png")
        x, y, w, h = self.bounds()
        if not crop(FULL_PATH, dst, x, y, w, h):
            self.flash("Gagal menyimpan gambar.")
            return
        log(f"saved {dst}")
        self.flash(f"Tersimpan: {dst}", ok=True, then_quit=True)

    def flash(self, msg, ok=False, then_quit=False):
        color = "#22ff66" if ok else "#ffdd22"
        self.canvas.itemconfig(self.hint_id, text=msg, fill=color)
        try:
            self.root.bell()
        except Exception:
            pass
        if then_quit:
            self.root.after(700, self.quit)

    def quit(self):
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
    SnapApp(root, w, h, DIM_PATH)
    root.mainloop()
    log("snap keluar")
    return 0


if __name__ == "__main__":
    sys.exit(main())
