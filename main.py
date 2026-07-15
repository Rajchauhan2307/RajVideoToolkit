"""
RAJ VIDEO TOOLKIT v2
Created By Raj - Content World
100% OFFLINE. No API, no key, no internet.
[1] Merge Video + Transitions (with preview)
[2] Frame Extract
"""

import os
import re
import json
import threading
import subprocess
import tempfile

import customtkinter as ctk
from tkinter import filedialog


def _ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".raj_video_toolkit")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config_v2.json")

DEFAULTS = {
    "transition": "fade",
    "trans_dur": 0.5,
    "quality": "TRUE LOSSLESS (CRF 0)",
    "batch": 5,
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

TRANSITIONS = [
    "none (lossless cut)",
    "fade",
    "fadeblack",
    "fadewhite",
    "dissolve",
    "slideleft",
    "slideright",
    "slideup",
    "slidedown",
    "wipeleft",
    "wiperight",
    "circleopen",
    "circleclose",
    "radial",
    "pixelize",
    "smoothleft",
    "smoothright",
    "zoomin",
    "hblur",
]


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def list_videos(folder):
    out = []
    for name in os.listdir(folder):
        p = os.path.join(folder, name)
        if os.path.isfile(p) and os.path.splitext(name)[1].lower() in VIDEO_EXTS:
            out.append(p)
    out.sort(key=lambda p: natural_key(os.path.basename(p)))
    return out


def run_cmd(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def probe_duration(path):
    ff = _ffmpeg_exe()
    r = run_cmd([ff, "-i", path])
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", r.stderr or "")
    if not m:
        return None
    h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return h * 3600 + mn * 60 + s


def probe_size_fps(path):
    ff = _ffmpeg_exe()
    r = run_cmd([ff, "-i", path])
    err = r.stderr or ""
    m = re.search(r"(\d{2,5})x(\d{2,5})", err)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (1080, 1920)
    f = re.search(r"(\d+(?:\.\d+)?)\s*fps", err)
    fps = float(f.group(1)) if f else 30.0
    return w, h, fps


def quality_args(quality):
    if quality.startswith("TRUE"):
        return ["-c:v", "libx264", "-preset", "medium", "-crf", "0",
                "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "14",
            "-pix_fmt", "yuv420p"]


def concat_lossless(paths, out_path, log):
    ff = _ffmpeg_exe()
    lf = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    try:
        for p in paths:
            lf.write("file '" + p.replace("'", "'\\''") + "'\n")
        lf.close()
        r = run_cmd([ff, "-y", "-f", "concat", "-safe", "0", "-i", lf.name,
                     "-c", "copy", out_path])
        if r.returncode == 0 and os.path.exists(out_path):
            return True
        log("   copy failed, re-encoding...")
        r = run_cmd([ff, "-y", "-f", "concat", "-safe", "0", "-i", lf.name,
                     "-c:v", "libx264", "-crf", "14", "-preset", "medium",
                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out_path])
        return r.returncode == 0 and os.path.exists(out_path)
    finally:
        try:
            os.unlink(lf.name)
        except Exception:
            pass


def concat_with_transition(paths, out_path, trans, dur, quality, log):
    """Chain xfade across N clips."""
    ff = _ffmpeg_exe()
    n = len(paths)
    if n == 1:
        return concat_lossless(paths, out_path, log)

    durs = []
    for p in paths:
        d = probe_duration(p)
        if d is None:
            log("   duration read fail: " + os.path.basename(p))
            return False
        durs.append(d)

    w, h, fps = probe_size_fps(paths[0])

    cmd = [ff, "-y"]
    for p in paths:
        cmd += ["-i", p]

    fc = []
    for i in range(n):
        fc.append(
            "[%d:v]scale=%d:%d:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=%s[v%d]"
            % (i, w, h, w, h, fps, i)
        )

    offset = durs[0] - dur
    last = "v0"
    for i in range(1, n):
        outlbl = "x%d" % i
        fc.append(
            "[%s][v%d]xfade=transition=%s:duration=%s:offset=%s[%s]"
            % (last, i, trans, dur, round(max(offset, 0.1), 3), outlbl)
        )
        last = outlbl
        if i < n - 1:
            offset += durs[i] - dur

    # audio: crossfade chain so audio length matches video exactly
    alast = "0:a"
    for i in range(1, n):
        albl = "ax%d" % i
        fc.append("[%s][%d:a]acrossfade=d=%s:c1=tri:c2=tri[%s]"
                  % (alast, i, dur, albl))
        alast = albl
    fc.append("[%s]anull[aout]" % alast)

    cmd += ["-filter_complex", ";".join(fc), "-map", "[" + last + "]"]
    r = run_cmd(cmd + ["-map", "[aout]"] + quality_args(quality) +
                ["-c:a", "aac", "-b:a", "256k", out_path])
    if r.returncode == 0 and os.path.exists(out_path):
        return True

    # retry video-only (some clips may have no audio)
    fc2 = fc[:-1]
    cmd2 = [ff, "-y"]
    for p in paths:
        cmd2 += ["-i", p]
    cmd2 += ["-filter_complex", ";".join(fc2), "-map", "[" + last + "]"]
    r2 = run_cmd(cmd2 + quality_args(quality) + ["-an", out_path])
    if r2.returncode != 0:
        log("   ffmpeg error: " + (r2.stderr or "")[-300:])
    return r2.returncode == 0 and os.path.exists(out_path)


def make_preview(v1, v2, trans, dur, out_path, log):
    """Short clip showing the actual join: tail of v1 + head of v2."""
    ff = _ffmpeg_exe()
    d1 = probe_duration(v1) or 3.0
    tail = min(2.5, max(dur + 0.6, d1 * 0.5))
    start1 = max(0, d1 - tail)
    head = 2.5

    w, h, fps = probe_size_fps(v1)
    cmd = [ff, "-y",
           "-ss", str(round(start1, 2)), "-i", v1,
           "-ss", "0", "-t", str(head), "-i", v2]

    fc = [
        "[0:v]scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=%s[a0]"
        % (w, h, w, h, fps),
        "[1:v]scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=%s[a1]"
        % (w, h, w, h, fps),
        "[a0][a1]xfade=transition=%s:duration=%s:offset=%s[vout]"
        % (trans, dur, round(max(tail - dur, 0.1), 3)),
    ]
    r = run_cmd(cmd + ["-filter_complex", ";".join(fc), "-map", "[vout]",
                       "-c:v", "libx264", "-crf", "20", "-preset", "ultrafast",
                       "-pix_fmt", "yuv420p", "-an", out_path])
    if r.returncode != 0:
        log("   preview error: " + (r.stderr or "")[-250:])
    return r.returncode == 0 and os.path.exists(out_path)


def batch_merge(videos, batch_size, out_folder, trans, dur, quality, log, progress=None):
    groups = [videos[i:i + batch_size] for i in range(0, len(videos), batch_size)]
    os.makedirs(out_folder, exist_ok=True)
    made = 0
    for gi, group in enumerate(groups, 1):
        stem, ext = os.path.splitext(os.path.basename(group[0]))
        if not ext:
            ext = ".mp4"
        out_path = os.path.join(out_folder, stem + ext)
        k = 1
        while os.path.exists(out_path):
            out_path = os.path.join(out_folder, stem + " (" + str(k) + ")" + ext)
            k += 1
        log("[" + str(gi) + "/" + str(len(groups)) + "] " + str(len(group)) +
            " clips -> " + os.path.basename(out_path))
        if trans == "none":
            ok = concat_lossless(group, out_path, log)
        else:
            ok = concat_with_transition(group, out_path, trans, dur, quality, log)
        if ok:
            made += 1
        else:
            log("   FAILED group " + str(gi))
        if progress:
            progress(gi / len(groups))
    return made, len(groups)


def extract_frames(video, mode, value, out_root, log):
    ff = _ffmpeg_exe()
    stem = os.path.splitext(os.path.basename(video))[0]
    outdir = os.path.join(out_root, stem)
    os.makedirs(outdir, exist_ok=True)
    pattern = os.path.join(outdir, "frame_%03d.jpg")

    if mode.startswith("Smart"):
        cmd = [ff, "-y", "-i", video, "-vf",
               "select='gt(scene,0.25)',scale=1280:-2", "-vsync", "vfr",
               "-q:v", "2", pattern]
        r = run_cmd(cmd)
        got = len(os.listdir(outdir))
        if got < 3:
            cmd = [ff, "-y", "-i", video, "-vf",
                   "fps=1/2,scale=1280:-2", "-q:v", "2", pattern]
            r = run_cmd(cmd)
    elif mode.startswith("Every"):
        cmd = [ff, "-y", "-i", video, "-vf",
               "fps=1/" + str(value) + ",scale=1280:-2", "-q:v", "2", pattern]
        r = run_cmd(cmd)
    else:
        d = probe_duration(video) or 10.0
        step = max(d / (value + 1), 0.05)
        cmd = [ff, "-y", "-i", video, "-vf",
               "fps=1/" + str(round(step, 3)) + ",scale=1280:-2",
               "-frames:v", str(value), "-q:v", "2", pattern]
        r = run_cmd(cmd)

    n = len([f for f in os.listdir(outdir) if f.endswith(".jpg")])
    log("   " + stem + " -> " + str(n) + " frames")
    return n


BG = "#0C1122"
PANEL = "#131A30"
PANEL2 = "#182140"
TEAL = "#38E3D0"
ORANGE = "#FF7A3C"
INK = "#EAEFFA"
MUTED = "#8894B8"

ctk.set_appearance_mode("dark")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.title("RAJ VIDEO TOOLKIT v2 - Content World")
        self.geometry("1020x680")
        self.configure(fg_color=BG)
        self.merge_folder = ""
        self.merge_out = ""
        self.fx_folder = ""
        self.fx_out = ""
        self._build_sidebar()
        self._build_main()
        self.show_panel("merge")

    def _build_sidebar(self):
        bar = ctk.CTkFrame(self, width=200, fg_color=PANEL, corner_radius=0)
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)
        ctk.CTkLabel(bar, text="RAJ VIDEO", font=("Arial Black", 17), text_color=INK).pack(pady=(22, 0))
        ctk.CTkLabel(bar, text="TOOLKIT v2", font=("Arial Black", 17), text_color=ORANGE).pack(pady=(0, 2))
        ctk.CTkLabel(bar, text="100% Offline", font=("Arial", 10), text_color=TEAL).pack(pady=(0, 18))
        self.nav_btns = {}
        for key, label in [("merge", "  Merge + Effects"), ("frames", "  Frame Extract")]:
            b = ctk.CTkButton(bar, text=label, anchor="w", height=44,
                              fg_color="transparent", hover_color=PANEL2,
                              text_color=MUTED, font=("Arial", 14),
                              command=lambda k=key: self.show_panel(k))
            b.pack(fill="x", padx=10, pady=3)
            self.nav_btns[key] = b
        ctk.CTkLabel(bar, text="No API  No Key", font=("Arial", 10),
                     text_color=MUTED).pack(side="bottom", pady=14)

    def _build_main(self):
        self.main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.main.pack(side="left", fill="both", expand=True)
        self.panels = {}
        self.panels["merge"] = self._panel_merge()
        self.panels["frames"] = self._panel_frames()
        lf = ctk.CTkFrame(self.main, fg_color=PANEL, height=140)
        lf.pack(side="bottom", fill="x", padx=16, pady=(0, 14))
        ctk.CTkLabel(lf, text="LOG", font=("Consolas", 11), text_color=MUTED).pack(anchor="w", padx=12, pady=(6, 0))
        self.logbox = ctk.CTkTextbox(lf, height=100, fg_color=BG, text_color=TEAL, font=("Consolas", 11))
        self.logbox.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.progress = ctk.CTkProgressBar(lf, progress_color=ORANGE)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=10, pady=(0, 8))

    def _header(self, parent, title, sub):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=6, pady=(4, 12))
        ctk.CTkLabel(f, text=title, font=("Arial Black", 22), text_color=INK).pack(anchor="w")
        ctk.CTkLabel(f, text=sub, font=("Arial", 12), text_color=MUTED,
                     wraplength=700, justify="left").pack(anchor="w")

    def _folder_row(self, parent, label, setter):
        row = ctk.CTkFrame(parent, fg_color=PANEL)
        row.pack(fill="x", padx=6, pady=5)
        lbl = ctk.CTkLabel(row, text=label + ": (not selected)", text_color=MUTED,
                           font=("Consolas", 11), anchor="w")
        lbl.pack(side="left", fill="x", expand=True, padx=12, pady=10)

        def pick():
            d = filedialog.askdirectory()
            if d:
                setter(d)
                lbl.configure(text=label + ": " + d, text_color=INK)

        ctk.CTkButton(row, text="Select", width=90, fg_color=PANEL2,
                      hover_color=TEAL, command=pick).pack(side="right", padx=10, pady=8)
        return lbl

    def _panel_merge(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color=BG)
        self._header(p, "Merge + Effects",
                     "Transition har clip ke JOD pe automatic lagega. Pehle PREVIEW dekho, phir merge. "
                     "Batch 5 -> har 5 clip ki ek video.")
        self._folder_row(p, "Source folder", lambda d: setattr(self, "merge_folder", d))
        self._folder_row(p, "Output folder", lambda d: setattr(self, "merge_out", d))

        box = ctk.CTkFrame(p, fg_color=PANEL)
        box.pack(fill="x", padx=6, pady=6)

        r1 = ctk.CTkFrame(box, fg_color="transparent")
        r1.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkLabel(r1, text="Transition:", text_color=MUTED, width=90, anchor="w").pack(side="left")
        self.trans_menu = ctk.CTkOptionMenu(r1, values=TRANSITIONS, width=210,
                                            fg_color=PANEL2, button_color=ORANGE)
        self.trans_menu.set(self.cfg.get("transition", "fade"))
        self.trans_menu.pack(side="left", padx=8)
        ctk.CTkButton(r1, text="PREVIEW", width=110, fg_color=TEAL, text_color=BG,
                      font=("Arial Black", 12), command=self.run_preview).pack(side="left", padx=8)

        r2 = ctk.CTkFrame(box, fg_color="transparent")
        r2.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(r2, text="Duration:", text_color=MUTED, width=90, anchor="w").pack(side="left")
        self.dur_lbl = ctk.CTkLabel(r2, text="0.5 s", text_color=TEAL, width=50)
        self.dur_slider = ctk.CTkSlider(r2, from_=0.2, to=2.0, number_of_steps=18,
                                        width=220, progress_color=ORANGE,
                                        command=self._dur_change)
        self.dur_slider.set(float(self.cfg.get("trans_dur", 0.5)))
        self.dur_slider.pack(side="left", padx=8)
        self.dur_lbl.pack(side="left")

        r3 = ctk.CTkFrame(box, fg_color="transparent")
        r3.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(r3, text="Quality:", text_color=MUTED, width=90, anchor="w").pack(side="left")
        self.qual_menu = ctk.CTkOptionMenu(r3, values=[
            "TRUE LOSSLESS (CRF 0)", "VISUAL LOSSLESS (CRF 14)"],
            width=250, fg_color=PANEL2, button_color=ORANGE)
        self.qual_menu.set(self.cfg.get("quality", "TRUE LOSSLESS (CRF 0)"))
        self.qual_menu.pack(side="left", padx=8)

        r4 = ctk.CTkFrame(box, fg_color="transparent")
        r4.pack(fill="x", padx=12, pady=(6, 12))
        ctk.CTkLabel(r4, text="Batch size:", text_color=MUTED, width=90, anchor="w").pack(side="left")
        self.batch_entry = ctk.CTkEntry(r4, width=80)
        self.batch_entry.insert(0, str(self.cfg.get("batch", 5)))
        self.batch_entry.pack(side="left", padx=8)
        ctk.CTkLabel(r4, text="(kitni video se ek bane)", text_color=MUTED).pack(side="left", padx=6)

        ctk.CTkButton(p, text="MERGE NOW", fg_color=ORANGE, hover_color="#ff9a5c",
                      font=("Arial Black", 15), width=180, height=42,
                      command=self.run_merge).pack(pady=16)
        return p

    def _dur_change(self, v):
        self.dur_lbl.configure(text=str(round(float(v), 1)) + " s")

    def _panel_frames(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color=BG)
        self._header(p, "Frame Extract",
                     "Kisi bhi video ke frames nikaalo - reference ke liye. "
                     "Har video ka apna folder banega.")
        self._folder_row(p, "Source folder", lambda d: setattr(self, "fx_folder", d))
        self._folder_row(p, "Output folder", lambda d: setattr(self, "fx_out", d))

        box = ctk.CTkFrame(p, fg_color=PANEL)
        box.pack(fill="x", padx=6, pady=6)
        r1 = ctk.CTkFrame(box, fg_color="transparent")
        r1.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkLabel(r1, text="Mode:", text_color=MUTED, width=80, anchor="w").pack(side="left")
        self.fx_mode = ctk.CTkOptionMenu(r1, values=[
            "Smart (auto best frames)",
            "Every X seconds",
            "Fixed count",
        ], width=230, fg_color=PANEL2, button_color=ORANGE)
        self.fx_mode.pack(side="left", padx=8)

        r2 = ctk.CTkFrame(box, fg_color="transparent")
        r2.pack(fill="x", padx=12, pady=(6, 12))
        ctk.CTkLabel(r2, text="Value:", text_color=MUTED, width=80, anchor="w").pack(side="left")
        self.fx_value = ctk.CTkEntry(r2, width=80)
        self.fx_value.insert(0, "10")
        self.fx_value.pack(side="left", padx=8)
        ctk.CTkLabel(r2, text="(seconds ya count - Smart me ignore)",
                     text_color=MUTED).pack(side="left", padx=6)

        ctk.CTkButton(p, text="EXTRACT FRAMES", fg_color=ORANGE, hover_color="#ff9a5c",
                      font=("Arial Black", 15), width=200, height=42,
                      command=self.run_frames).pack(pady=16)
        return p

    def show_panel(self, key):
        for k, b in self.nav_btns.items():
            b.configure(fg_color=(ORANGE if k == key else "transparent"),
                        text_color=(BG if k == key else MUTED))
        for k, pnl in self.panels.items():
            pnl.pack_forget()
        self.panels[key].pack(side="top", fill="both", expand=True, padx=10, pady=10)

    def log(self, msg):
        self.after(0, lambda: (self.logbox.insert("end", msg + "\n"), self.logbox.see("end")))

    def set_progress(self, v):
        self.after(0, lambda: self.progress.set(v))

    def _save(self):
        self.cfg["transition"] = self.trans_menu.get()
        self.cfg["trans_dur"] = round(float(self.dur_slider.get()), 2)
        self.cfg["quality"] = self.qual_menu.get()
        try:
            self.cfg["batch"] = int(self.batch_entry.get())
        except Exception:
            self.cfg["batch"] = 5
        save_config(self.cfg)

    def _trans_name(self):
        t = self.trans_menu.get()
        return "none" if t.startswith("none") else t

    def _run_thread(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def run_preview(self):
        self._save()
        folder = self.merge_folder
        if not folder:
            self.log("Source folder select karo.")
            return
        trans = self._trans_name()
        if trans == "none":
            self.log("'none' me koi transition nahi - preview ki zarurat nahi.")
            return
        dur = round(float(self.dur_slider.get()), 2)

        def work():
            vids = list_videos(folder)
            if len(vids) < 2:
                self.log("Preview ke liye kam se kam 2 video chahiye.")
                return
            self.log("Preview bana raha hun (" + trans + ", " + str(dur) + "s)...")
            out = os.path.join(tempfile.gettempdir(), "raj_preview.mp4")
            if make_preview(vids[0], vids[1], trans, dur, out, self.log):
                self.log("Preview ready - khul raha hai...")
                try:
                    os.startfile(out)
                except Exception:
                    self.log("Kholo: " + out)
            else:
                self.log("Preview fail hua.")

        self._run_thread(work)

    def run_merge(self):
        self._save()
        folder = self.merge_folder
        out_folder = self.merge_out or folder
        if not folder:
            self.log("Source folder select karo.")
            return
        trans = self._trans_name()
        dur = round(float(self.dur_slider.get()), 2)
        quality = self.qual_menu.get()
        try:
            bs = int(self.batch_entry.get())
        except Exception:
            bs = 5

        def work():
            vids = list_videos(folder)
            if not vids:
                self.log("Folder me koi video nahi mili.")
                return
            self.log(str(len(vids)) + " videos | batch " + str(bs) +
                     " | " + trans + " | " + quality)
            made, total = batch_merge(vids, bs, out_folder, trans, dur, quality,
                                      self.log, self.set_progress)
            self.log("DONE -> " + str(made) + "/" + str(total) + " videos in " + out_folder)

        self._run_thread(work)

    def run_frames(self):
        folder = self.fx_folder
        out_folder = self.fx_out or folder
        if not folder:
            self.log("Source folder select karo.")
            return
        mode = self.fx_mode.get()
        try:
            val = int(self.fx_value.get())
        except Exception:
            val = 10

        def work():
            vids = list_videos(folder)
            if not vids:
                self.log("Folder me koi video nahi mili.")
                return
            self.log(str(len(vids)) + " videos | " + mode)
            os.makedirs(out_folder, exist_ok=True)
            total = 0
            for i, v in enumerate(vids, 1):
                self.log("[" + str(i) + "/" + str(len(vids)) + "] " + os.path.basename(v))
                total += extract_frames(v, mode, val, out_folder, self.log)
                self.set_progress(i / len(vids))
            self.log("DONE -> " + str(total) + " frames in " + out_folder)

        self._run_thread(work)


if __name__ == "__main__":
    App().mainloop()
