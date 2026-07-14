"""
RAJ VIDEO TOOLKIT
Created By Raj - Content World
"""

import os
import re
import sys
import json
import time
import threading
import subprocess
import tempfile
from pathlib import Path

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
    t = t.replace("\u201c", '').replace("\u201d", '').replace("\u2018", "'").replace("\u2019", "'")
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

    def _spell(self):
        return "US" if self.cfg.get("spelling", "US") == "US" else "UK"

    def _human_rules(self):
        sp = self._spell()
        spell_txt = ("Use US English spelling (color, favorite)."
                     if sp == "US" else
                     "Use UK English spelling (colour, favourite).")
        return (
            "STRICT WRITING RULES:\n"
            "- Write like a real human creator for a US/UK audience. It must NOT look AI-generated.\n"
            f"- {spell_txt} Native, natural English only. No Hindi/Hinglish.\n"
            "- NEVER use the word 'AI' anywhere.\n"
            "- Ban these AI-tell words: delve, unleash, elevate, dive into, embark, "
            "tapestry, testament, in this video, let's, realm, boasts, ever-evolving.\n"
            "- No em dash. Use a normal hyphen '-'. Use straight quotes only.\n"
            "- Vary length and structure across items. No robotic repeated pattern.\n"
            f"- NEVER use these characters: {ILLEGAL}\n"
        )

    def _call(self, parts, retries=3):
        last = None
        for attempt in range(retries):
            try:
                resp = self.client.models.generate_content(
                    model=self.cfg["model"], contents=parts
                )
                return (resp.text or "").strip()
