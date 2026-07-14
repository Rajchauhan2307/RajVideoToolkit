"""
RAJ VIDEO TOOLKIT
Created By Raj - Content World
"""

import os
import re
import json
import time
import threading
import subprocess
import tempfile

import customtkinter as ctk
from tkinter import filedialog


def _lazy_cv2():
    import cv2
    return cv2

def _lazy_pil():
    from PIL import Image
    return Image

def _lazy_genai():
    from google import genai
    return genai

def _ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".raj_video_toolkit")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "api_key": "",
    "model": "gemini-2.5-flash",
    "spelling": "US",
    "rpm_delay": 4.2,
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
ILLEGAL = r'\/:*?"<>|'

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

def clean_title_for_upload(title, max_len=100):
    t = "".join(ch for ch in title if ch not in ILLEGAL)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace("\u2014", "-").replace("\u2013", "-")
    t = t.replace("\u201c", "").replace("\u201d", "")
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    if len(t) > max_len:
        t = t[:max_len].rsplit(" ", 1)[0].strip()
    return t

def clean_title_for_filename(title, max_len=70):
    t = clean_title_for_upload(title, max_len=max_len)
    t = t.rstrip(". ")
    return t or "video"

def extract_frames(video_path, n=3):
    cv2 = _lazy_cv2()
    Image = _lazy_pil()
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    frames = []
    if total <= 0:
        for _ in range(n):
            ok, fr = cap.read()
            if not ok:
                break
            frames.append(fr)
    else:
        for i in range(n):
            pos = int(total * (i + 0.5) / n)
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ok, fr = cap.read()
            if ok:
                frames.append(fr)
    cap.release()
    pil = []
    for fr in frames:
        rgb = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        img.thumbnail((640, 640))
        pil.append(img)
    return pil


class GeminiEngine:
    def __init__(self, cfg):
        self.cfg = cfg
        self.client = None

    def connect(self):
        genai = _lazy_genai()
        self.client = genai.Client(api_key=self.cfg["api_key"])

    def _human_rules(self):
        sp = self.cfg.get("spelling", "US")
        spell_txt = ("Use US English spelling (color, favorite)."
                     if sp == "US" else
                     "Use UK English spelling (colour, favourite).")
        return (
            "STRICT WRITING RULES:\n"
            "- Write like a real human creator for a US/UK audience. It must NOT look AI-generated.\n"
            "- " + spell_txt + " Native, natural English only. No Hindi/Hinglish.\n"
            "- NEVER use the word 'AI' anywhere.\n"
            "- Ban these AI-tell words: delve, unleash, elevate, dive into, embark, "
            "tapestry, testament, in this video, realm, boasts, ever-evolving.\n"
            "- No em dash. Use a normal hyphen. Use straight quotes only.\n"
            "- Vary length and structure across items. No robotic repeated pattern.\n"
            "- NEVER use these characters: " + ILLEGAL + "\n"
        )

    def _call(self, parts, retries=3):
        last = None
        for attempt in range(retries):
            try:
                resp = self.client.models.generate_content(
                    model=self.cfg["model"], contents=parts
                )
                return (resp.text or "").strip()
            except Exception as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise last

    def detect_niche(self, frames_lists):
        parts = [
            "Look at these frames sampled from several short videos. "
            "In ONE short line, name the exact content niche/topic. "
            "Reply with only the niche name, nothing else.\n"
        ]
        for fl in frames_lists:
            parts.extend(fl)
        return self._call(parts)

    def sample_titles(self, frames):
        prompt = (
            "From these video frames, understand the niche, then write 4 sample "
            "VIRAL video titles, one for EACH style below, so I can pick a style:\n"
            "A) Emotional  B) Curiosity gap  C) Number hook  D) Direct\n"
            + self._human_rules() +
            "- Keep each title under 100 characters (YouTube limit).\n"
            "Output exactly 4 lines, format: 'A) title' 'B) title' 'C) title' 'D) title'.\n"
        )
        return self._call([prompt] + list(frames))

    def titles(self, frames, count, style, want_hashtags):
        style_map = {
            "Mixed": "Mix all viral styles (emotional, curiosity, number, direct).",
            "Emotional": "Emotional / story hook style.",
            "Curiosity": "Curiosity-gap style.",
            "Number Hook": "Number-hook style.",
            "Direct": "Clean direct style.",
        }
        prompt = (
            "From these video frames, understand the niche and write " + str(count) + " "
            "VIRAL, human-style video titles. Style: " + style_map.get(style, style_map["Mixed"]) + "\n"
            + self._human_rules() +
            "- Keep each title under 100 characters (YouTube limit).\n"
            "- Use real viral hooks (curiosity, numbers, emotion, eye-contact, pattern interrupt).\n"
            "Output ONLY the titles, one per line, numbered 1.." + str(count)
            + (", each line as: title ::: #tag #tag #tag\n" if want_hashtags else ".\n")
        )
        return self._call([prompt] + list(frames))

    def one_title(self, frames, want_hashtags):
        prompt = (
            "From these frames of ONE short video, write ONE viral, human-style "
            "title for a US/UK audience.\n"
            + self._human_rules() +
            "- Under 100 characters.\n"
            + ("Output as: title ::: #tag #tag #tag  (one line only)\n"
               if want_hashtags else "Output only the title, one line, nothing else.\n")
        )
        return self._call([prompt] + list(frames))

    def seo(self, frames):
        prompt = (
            "From these video frames, build a complete SEO pack for a US/UK audience. "
            "Make it sound like a real human creator wrote it (must not look AI-generated).\n"
            + self._human_rules() +
            "Return in this exact layout:\n"
            "DESCRIPTION:\n<3-5 natural lines with a hook, then a casual CTA>\n\n"
            "TAGS:\n<15-20 comma separated tags>\n\n"
            "KEYWORDS:\n<10-15 real search keywords, comma separated>\n"
        )
        return self._call([prompt] + list(frames))

    def image_prompts(self, frames, name, selections):
        name = (name or "").strip()
        if name:
            name_rule = 'Put the channel name "' + name + '" as the main text, centered inside the safe zone.'
        else:
            name_rule = "Do NOT put any text or channel name. Pure visual only, niche-themed icon/scene."
        blocks = []
        if "FB DP" in selections:
            blocks.append("FB PROFILE PICTURE - 1:1 square (design at 1024x1024). "
                          "Key element centered and circle-safe.")
        if "FB Cover" in selections:
            blocks.append("FB COVER - 851x315 ratio (design at 1640x924). Key content centered, avoid far edges.")
        if "YT DP" in selections:
            blocks.append("YT PROFILE PICTURE - 1:1 square (design at 800x800). Circle-safe, centered.")
        if "YT Banner" in selections:
            blocks.append(
                "YT BANNER - EXACT 2560x1440, 16:9. STRICT SAFE ZONE RULE (never break): "
                "ALL important elements (logo text, name, tagline, main subject) MUST sit fully inside "
                "a centered horizontal safe band of 1546x423 px in the exact middle. Keep them COMPACT and "
                "centered. NOTHING important may touch top, bottom, left or right edges. The OUTER area "
                "must contain ONLY a soft, blurred, darkened, cinematic decorative background matching the "
                "niche - absolutely NO text, NO logos, NO readable detail there."
            )
        prompt = (
            "From these video frames, understand the niche. Then write a SEPARATE, highly-detailed, "
            "professional image-generation PROMPT for EACH item below. Each prompt must be strict and fully "
            "described so even a weak image tool follows it: describe scene, subject, colors, lighting, "
            "depth, mood, premium cinematic high-contrast look, and exact size rules. Use strong MUST / NEVER "
            "language. Aim for premium quality, not basic.\n"
            "TEXT RULE: " + name_rule + "\n"
            + self._human_rules() +
            "\nITEMS:\n- " + "\n- ".join(blocks) +
            "\n\nOutput each as:\n=== <ITEM NAME> ===\n<full prompt>\n"
        )
        return self._call([prompt] + list(frames))


def split_title_tags(line):
    if ":::" in line:
        t, h = line.split(":::", 1)
        return t.strip(), h.strip()
    return line.strip(), ""


def merge_group(paths, out_path, log):
    ff = _ffmpeg_exe()
    listfile = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    try:
        for p in paths:
            safe = p.replace("'", "'\\''")
            listfile.write("file '" + safe + "'\n")
        listfile.close()
        cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", listfile.name,
               "-c", "copy", out_path]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(out_path):
            log("   lossless copy failed, re-encoding to match...")
            cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", listfile.name,
                   "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                   "-c:a", "aac", "-b:a", "192k", out_path]
            r = subprocess.run(cmd, capture_output=True, text=True)
        return r.returncode == 0 and os.path.exists(out_path)
    finally:
        try:
            os.unlink(listfile.name)
        except Exception:
            pass

def batch_merge(videos, batch_size, out_folder, log, progress=None):
    groups = [videos[i:i + batch_size] for i in range(0, len(videos), batch_size)]
    os.makedirs(out_folder, exist_ok=True)
    done = 0
    made = 0
    for gi, group in enumerate(groups, 1):
        first = os.path.basename(group[0])
        stem, ext = os.path.splitext(first)
        if not ext:
            ext = ".mp4"
        out_path = os.path.join(out_folder, stem + ext)
        n = 1
        while os.path.exists(out_path):
            out_path = os.path.join(out_folder, stem + " (" + str(n) + ")" + ext)
            n += 1
        log("[" + str(gi) + "/" + str(len(groups)) + "] merging " + str(len(group)) +
            " clips -> " + os.path.basename(out_path))
        if merge_group(group, out_path, log):
            made += 1
        else:
            log("   FAILED on group " + str(gi))
        done += 1
        if progress:
            progress(done / len(groups))
    return made, len(groups)


BG      = "#0C1122"
PANEL   = "#131A30"
PANEL2  = "#182140"
TEAL    = "#38E3D0"
ORANGE  = "#FF7A3C"
INK     = "#EAEFFA"
MUTED   = "#8894B8"

ctk.set_appearance_mode("dark")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()
        self.engine = GeminiEngine(self.cfg)
        self.title("RAJ VIDEO TOOLKIT - Content World")
        self.geometry("1060x680")
        self.configure(fg_color=BG)
        self.title_folder = ""
        self.title_out = ""
        self.seo_folder = ""
        self.seo_out = ""
        self.img_folder = ""
        self.img_out = ""
        self.merge_folder = ""
        self.merge_out = ""
        self._build_sidebar()
        self._build_main()
        self.show_panel("title")

    def _build_sidebar(self):
        bar = ctk.CTkFrame(self, width=210, fg_color=PANEL, corner_radius=0)
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)
        ctk.CTkLabel(bar, text="RAJ VIDEO", font=("Arial Black", 18), text_color=INK).pack(pady=(22, 0))
        ctk.CTkLabel(bar, text="TOOLKIT", font=("Arial Black", 18), text_color=ORANGE).pack(pady=(0, 2))
        ctk.CTkLabel(bar, text="Content World", font=("Arial", 10), text_color=MUTED).pack(pady=(0, 18))
        self.nav_btns = {}
        items = [
            ("title", "  Title + Hashtag"),
            ("seo", "  SEO Pack"),
            ("image", "  Channel Image"),
            ("merge", "  Merge Video"),
            ("settings", "  Settings / Key"),
        ]
        for key, label in items:
            b = ctk.CTkButton(bar, text=label, anchor="w", height=42,
                              fg_color="transparent", hover_color=PANEL2,
                              text_color=MUTED, font=("Arial", 14),
                              command=lambda k=key: self.show_panel(k))
            b.pack(fill="x", padx=10, pady=3)
            self.nav_btns[key] = b
        self.key_lbl = ctk.CTkLabel(bar, text=self._key_status(), font=("Arial", 10), text_color=TEAL)
        self.key_lbl.pack(side="bottom", pady=14)

    def _key_status(self):
        return "Key: saved OK" if self.cfg.get("api_key") else "Key: NOT set"

    def _build_main(self):
        self.main = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.main.pack(side="left", fill="both", expand=True)
        self.panels = {}
        self.panels["title"] = self._panel_title()
        self.panels["seo"] = self._panel_seo()
        self.panels["image"] = self._panel_image()
        self.panels["merge"] = self._panel_merge()
        self.panels["settings"] = self._panel_settings()
        lf = ctk.CTkFrame(self.main, fg_color=PANEL, height=150)
        lf.pack(side="bottom", fill="x", padx=16, pady=(0, 14))
        ctk.CTkLabel(lf, text="LOG", font=("Consolas", 11), text_color=MUTED).pack(anchor="w", padx=12, pady=(6, 0))
        self.logbox = ctk.CTkTextbox(lf, height=110, fg_color=BG, text_color=TEAL, font=("Consolas", 11))
        self.logbox.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.progress = ctk.CTkProgressBar(lf, progress_color=ORANGE)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=10, pady=(0, 8))

    def _header(self, parent, title, sub):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=6, pady=(4, 12))
        ctk.CTkLabel(f, text=title, font=("Arial Black", 22), text_color=INK).pack(anchor="w")
        ctk.CTkLabel(f, text=sub, font=("Arial", 12), text_color=MUTED,
                     wraplength=720, justify="left").pack(anchor="w")

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

    def _panel_title(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color=BG)
        self._header(p, "Title + Hashtag",
                     "Video scan karke niche samajhega. 3 modes - sample, full folder, ya scan+rename.")
        self._folder_row(p, "Source folder", lambda d: setattr(self, "title_folder", d))
        self._folder_row(p, "Output folder", lambda d: setattr(self, "title_out", d))
        opt = ctk.CTkFrame(p, fg_color=PANEL)
        opt.pack(fill="x", padx=6, pady=6)
        self.title_mode = ctk.CTkOptionMenu(opt, values=[
            "1) Sample scan (15-20) -> title ideas",
            "2) Full folder -> title per video (.txt)",
            "3) Scan + RENAME videos",
        ], fg_color=PANEL2, button_color=ORANGE)
        self.title_mode.pack(fill="x", padx=12, pady=(12, 6))
        row2 = ctk.CTkFrame(opt, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(row2, text="Style:", text_color=MUTED).pack(side="left")
        self.title_style = ctk.CTkOptionMenu(row2, values=[
            "Mixed", "Emotional", "Curiosity", "Number Hook", "Direct"],
            fg_color=PANEL2, button_color=ORANGE, width=150)
        self.title_style.pack(side="left", padx=8)
        ctk.CTkLabel(row2, text="Count:", text_color=MUTED).pack(side="left", padx=(16, 0))
        self.title_count = ctk.CTkEntry(row2, width=70)
        self.title_count.insert(0, "50")
        self.title_count.pack(side="left", padx=8)
        row3 = ctk.CTkFrame(opt, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=(6, 12))
        self.title_hash = ctk.CTkSwitch(row3, text="Add hashtags", progress_color=ORANGE)
        self.title_hash.select()
        self.title_hash.pack(side="left")
        self.spell_switch = ctk.CTkSwitch(row3, text="UK spelling (off = US)", progress_color=TEAL)
        if self.cfg.get("spelling") == "UK":
            self.spell_switch.select()
        self.spell_switch.pack(side="left", padx=20)
        btns = ctk.CTkFrame(p, fg_color="transparent")
        btns.pack(fill="x", padx=6, pady=8)
        ctk.CTkButton(btns, text="Preview sample styles", fg_color=PANEL2,
                      hover_color=TEAL, command=self.run_preview).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="RUN", fg_color=ORANGE, hover_color="#ff9a5c",
                      font=("Arial Black", 14), width=140,
                      command=self.run_title).pack(side="right", padx=4)
        return p

    def _panel_seo(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color=BG)
        self._header(p, "SEO Pack",
                     "Video scan -> Description + Tags + Keywords, human-style, ek .txt me.")
        self._folder_row(p, "Source folder", lambda d: setattr(self, "seo_folder", d))
        self._folder_row(p, "Output folder", lambda d: setattr(self, "seo_out", d))
        ctk.CTkButton(p, text="RUN", fg_color=ORANGE, hover_color="#ff9a5c",
                      font=("Arial Black", 14), width=140, command=self.run_seo).pack(pady=14)
        return p

    def _panel_image(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color=BG)
        self._header(p, "Channel Image Prompt",
                     "Video scan -> niche. Naam do to logo pe aayega, khaali chhodo to sirf niche-visual (no text).")
        self._folder_row(p, "Source folder", lambda d: setattr(self, "img_folder", d))
        self._folder_row(p, "Output folder", lambda d: setattr(self, "img_out", d))
        namef = ctk.CTkFrame(p, fg_color=PANEL)
        namef.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(namef, text="Channel/Page name (optional):",
                     text_color=MUTED).pack(anchor="w", padx=12, pady=(10, 0))
        self.img_name = ctk.CTkEntry(namef, placeholder_text="Khaali = bina naam ka DP")
        self.img_name.pack(fill="x", padx=12, pady=(4, 12))
        chk = ctk.CTkFrame(p, fg_color=PANEL)
        chk.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(chk, text="Kya banana hai?", text_color=MUTED).pack(anchor="w", padx=12, pady=(10, 4))
        self.img_checks = {}
        for nm in ["FB DP", "FB Cover", "YT DP", "YT Banner"]:
            c = ctk.CTkCheckBox(chk, text=nm, fg_color=TEAL)
            c.pack(anchor="w", padx=16, pady=3)
            self.img_checks[nm] = c
        self.img_checks["YT Banner"].select()
        ctk.CTkButton(p, text="RUN", fg_color=ORANGE, hover_color="#ff9a5c",
                      font=("Arial Black", 14), width=140, command=self.run_image).pack(pady=14)
        return p

    def _panel_merge(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color=BG)
        self._header(p, "Merge Video (batch)",
                     "Batch size set karo. 80 video, batch 5 -> 16 merged. Naam = har group ki pehli video. Lossless.")
        self._folder_row(p, "Source folder", lambda d: setattr(self, "merge_folder", d))
        self._folder_row(p, "Output folder", lambda d: setattr(self, "merge_out", d))
        row = ctk.CTkFrame(p, fg_color=PANEL)
        row.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(row, text="Batch size (kitni video se ek bane):",
                     text_color=MUTED).pack(side="left", padx=12, pady=12)
        self.merge_batch = ctk.CTkEntry(row, width=80)
        self.merge_batch.insert(0, "5")
        self.merge_batch.pack(side="left", padx=8)
        ctk.CTkButton(p, text="MERGE NOW", fg_color=ORANGE, hover_color="#ff9a5c",
                      font=("Arial Black", 14), width=160, command=self.run_merge).pack(pady=14)
        return p

    def _panel_settings(self):
        p = ctk.CTkScrollableFrame(self.main, fg_color=BG)
        self._header(p, "Settings / API Key",
                     "Gemini free key ek baar daalo - app save kar lega. aistudio.google.com se free milti hai.")
        box = ctk.CTkFrame(p, fg_color=PANEL)
        box.pack(fill="x", padx=6, pady=8)
        ctk.CTkLabel(box, text="Gemini API Key", text_color=MUTED).pack(anchor="w", padx=12, pady=(12, 2))
        self.key_entry = ctk.CTkEntry(box, show="*")
        self.key_entry.insert(0, self.cfg.get("api_key", ""))
        self.key_entry.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(box, text="Model", text_color=MUTED).pack(anchor="w", padx=12, pady=(10, 2))
        self.model_menu = ctk.CTkOptionMenu(box, values=["gemini-2.5-flash", "gemini-2.5-flash-lite"],
                                            fg_color=PANEL2, button_color=ORANGE)
        self.model_menu.set(self.cfg.get("model", "gemini-2.5-flash"))
        self.model_menu.pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(box, text="Save", fg_color=ORANGE, hover_color="#ff9a5c",
                      command=self.save_settings).pack(pady=14)
        return p

    def show_panel(self, key):
        for k, b in self.nav_btns.items():
            b.configure(fg_color=(ORANGE if k == key else "transparent"),
                        text_color=(BG if k == key else MUTED))
        for k, pnl in self.panels.items():
            pnl.pack_forget()
        self.panels[key].pack(side="top", fill="both", expand=True, padx=10, pady=10)

    def log(self, msg):
        def _do():
            self.logbox.insert("end", msg + "\n")
            self.logbox.see("end")
        self.after(0, _do)

    def set_progress(self, v):
        self.after(0, lambda: self.progress.set(v))

    def save_settings(self):
        self.cfg["api_key"] = self.key_entry.get().strip()
        self.cfg["model"] = self.model_menu.get()
        save_config(self.cfg)
        self.key_lbl.configure(text=self._key_status())
        self.log("Settings saved.")

    def _sync_spelling(self):
        self.cfg["spelling"] = "UK" if self.spell_switch.get() else "US"
        save_config(self.cfg)

    def _ensure_key(self):
        if not self.cfg.get("api_key"):
            self.log("ERROR: pehle Settings me Gemini API key daalo.")
            return False
        try:
            self.engine.connect()
            return True
        except Exception as e:
            self.log("ERROR connecting: " + str(e))
            return False

    def _run_thread(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def _delay(self):
        time.sleep(float(self.cfg.get("rpm_delay", 4.2)))

    def run_preview(self):
        if not self._ensure_key():
            return
        self._sync_spelling()
        folder = self.title_folder
        if not folder:
            self.log("Source folder select karo.")
            return

        def work():
            vids = list_videos(folder)
            if not vids:
                self.log("Folder me koi video nahi mili.")
                return
            self.log("Scanning sample for style preview...")
            frames = extract_frames(vids[0], 3)
            try:
                out = self.engine.sample_titles(frames)
                self.log("SAMPLE STYLES:\n" + out)
            except Exception as e:
                self.log("ERROR: " + str(e))

        self._run_thread(work)

    def run_title(self):
        if not self._ensure_key():
            return
        self._sync_spelling()
        folder = self.title_folder
        out_folder = self.title_out or folder
        mode = self.title_mode.get()
        want_hash = bool(self.title_hash.get())
        if not folder:
            self.log("Source folder select karo.")
            return

        def work():
            vids = list_videos(folder)
            if not vids:
                self.log("Folder me koi video nahi mili.")
                return
            self.log(str(len(vids)) + " videos mili.")

            if mode.startswith("1"):
                try:
                    count = int(self.title_count.get())
                except Exception:
                    count = 50
                sample = vids[:20]
                frames_lists = []
                for i, v in enumerate(sample, 1):
                    self.log("scan " + str(i) + "/" + str(len(sample)))
                    frames_lists.append(extract_frames(v, 2))
                    self.set_progress(i / len(sample))
                try:
                    niche = self.engine.detect_niche(frames_lists)
                    self.log("NICHE: " + niche)
                    flat = [im for fl in frames_lists[:5] for im in fl]
                    out = self.engine.titles(flat, count, self.title_style.get(), want_hash)
                except Exception as e:
                    self.log("ERROR: " + str(e))
                    return
                path = os.path.join(out_folder, "titles.txt")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(out.strip() + "\n")
                self.log("DONE -> " + path)
                self.set_progress(1)
                return

            if mode.startswith("2"):
                lines = []
                for i, v in enumerate(vids, 1):
                    self.log("title " + str(i) + "/" + str(len(vids)) + " : " + os.path.basename(v))
                    frames = extract_frames(v, 3)
                    try:
                        raw = self.engine.one_title(frames, want_hash)
                    except Exception as e:
                        self.log("   skip (" + str(e) + ")")
                        continue
                    t, h = split_title_tags(raw)
                    t = clean_title_for_upload(t)
                    line = os.path.basename(v) + " ::: " + t
                    if h:
                        line += " ::: " + h
                    lines.append(line)
                    self.set_progress(i / len(vids))
                    self._delay()
                path = os.path.join(out_folder, "titles_mapped.txt")
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
                self.log("DONE -> " + path)
                self.set_progress(1)
                return

            if mode.startswith("3"):
                backup = []
                used = set()
                for i, v in enumerate(vids, 1):
                    self.log("rename " + str(i) + "/" + str(len(vids)) + " : " + os.path.basename(v))
                    frames = extract_frames(v, 3)
                    try:
                        raw = self.engine.one_title(frames, False)
                    except Exception as e:
                        self.log("   skip (" + str(e) + ")")
                        continue
                    t, _ = split_title_tags(raw)
                    ext = os.path.splitext(v)[1]
                    base = clean_title_for_filename(t)
                    new_name = base + ext
                    n = 1
                    while new_name.lower() in used or os.path.exists(os.path.join(folder, new_name)):
                        new_name = base + " (" + str(n) + ")" + ext
                        n += 1
                    used.add(new_name.lower())
                    new_path = os.path.join(folder, new_name)
                    try:
                        old_name = os.path.basename(v)
                        os.rename(v, new_path)
                        backup.append(old_name + " ::: " + new_name)
                    except Exception as e:
                        self.log("   rename fail (" + str(e) + ")")
                    self.set_progress(i / len(vids))
                    self._delay()
                bpath = os.path.join(out_folder, "rename_backup.txt")
                with open(bpath, "w", encoding="utf-8") as f:
                    f.write("OLD ::: NEW\n" + "\n".join(backup) + "\n")
                self.log("DONE. Backup -> " + bpath)
                self.set_progress(1)
                return

        self._run_thread(work)

    def run_seo(self):
        if not self._ensure_key():
            return
        self._sync_spelling()
        folder = self.seo_folder
        out_folder = self.seo_out or folder
        if not folder:
            self.log("Source folder select karo.")
            return

        def work():
            vids = list_videos(folder)
            if not vids:
                self.log("Folder me koi video nahi mili.")
                return
            path = os.path.join(out_folder, "seo_pack.txt")
            with open(path, "w", encoding="utf-8") as f:
                for i, v in enumerate(vids, 1):
                    self.log("SEO " + str(i) + "/" + str(len(vids)) + " : " + os.path.basename(v))
                    frames = extract_frames(v, 3)
                    try:
                        out = self.engine.seo(frames)
                    except Exception as e:
                        self.log("   skip (" + str(e) + ")")
                        continue
                    f.write("===== " + os.path.basename(v) + " =====\n" + out.strip() + "\n\n")
                    self.set_progress(i / len(vids))
                    self._delay()
            self.log("DONE -> " + path)
            self.set_progress(1)

        self._run_thread(work)

    def run_image(self):
        if not self._ensure_key():
            return
        self._sync_spelling()
        folder = self.img_folder
        out_folder = self.img_out or folder
        selections = [k for k, c in self.img_checks.items() if c.get()]
        if not folder:
            self.log("Source folder select karo.")
            return
        if not selections:
            self.log("Kam se kam ek image type tick karo.")
            return

        def work():
            vids = list_videos(folder)
            if not vids:
                self.log("Folder me koi video nahi mili.")
                return
            self.log("Scanning niche...")
            frames = extract_frames(vids[0], 3)
            try:
                out = self.engine.image_prompts(frames, self.img_name.get(), selections)
            except Exception as e:
                self.log("ERROR: " + str(e))
                return
            path = os.path.join(out_folder, "image_prompts.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(out.strip() + "\n")
            self.log("DONE -> " + path)
            self.set_progress(1)

        self._run_thread(work)

    def run_merge(self):
        folder = self.merge_folder
        out_folder = self.merge_out or folder
        if not folder:
            self.log("Source folder select karo.")
            return
        try:
            bs = int(self.merge_batch.get())
        except Exception:
            bs = 5

        def work():
            vids = list_videos(folder)
            if not vids:
                self.log("Folder me koi video nahi mili.")
                return
            self.log(str(len(vids)) + " videos, batch " + str(bs) + "...")
            made, total = batch_merge(vids, bs, out_folder, self.log, self.set_progress)
            self.log("DONE -> " + str(made) + "/" + str(total) + " merged videos in " + out_folder)

        self._run_thread(work)


if __name__ == "__main__":
    App().mainloop()
