import asyncio
from rapidfuzz import fuzz
import json
from pathlib import Path
import sys
import os
import re
from num2words import num2words
import subprocess
import glob
import configparser
import shlex
import random
import shutil
import unicodedata
import urllib.request
import tempfile

from voice_assistant import config


async def check_sim(text, target, thr = 75):
    text = text.lower().strip()
    target = target.lower().strip()
    score = fuzz.token_sort_ratio(text, target)
    return score >= thr, score


async def run_blocking(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)


def stem_word(word, morph):
    return morph.parse(word)[0].normal_form


def launch_app(command: str):
    subprocess.Popen(["command"], start_new_session=True)


def get_installed_apps():
    dirs = [
        "/usr/share/applications",
        "/usr/local/share/applications",
        str(Path.home() / ".local/share/applications"),
        "/var/lib/snapd/desktop/applications/"
    ]
    apps = {}
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*.desktop")):
            try:
                cp = configparser.ConfigParser(interpolation=None, strict=False)
                cp.read(f, encoding="utf-8")
                if "Desktop Entry" not in cp:
                    continue
                entry = cp["Desktop Entry"]
                if entry.get("NoDisplay", "false").strip().lower() == "true":
                    continue
                if entry.get("Hidden", "false").strip().lower() == "true":
                    continue
                if entry.get("Type", "Application") != "Application":
                    continue
                name = entry.get("Name")
                exec_cmd = entry.get("Exec")
                if not name or not exec_cmd:
                    continue
                exec_clean = re.sub(r"%[a-zA-Z]", "", exec_cmd).strip()
                apps[name] = exec_clean
            except Exception:
                continue
    return sorted(apps.items(), key=lambda x: x[0].lower())

def load_known_apps():
    if not os.path.exists(config.KNOWN_APPS_FILE):
        return {}
    try:
        with open(config.KNOWN_APPS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_known_apps(data):
    with open(config.KNOWN_APPS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _grim_available() -> bool:
    return shutil.which("grim") is not None


def _grim_capture(path: str):
    subprocess.run(["grim", path], check=True, timeout=10)


def _scrot_available() -> bool:
    return shutil.which("scrot") is not None


def _scrot_capture(path: str):
    subprocess.run(["scrot", "-o", path], check=True, timeout=10)


def _import_available() -> bool:
    return shutil.which("import") is not None


def _import_capture(path: str):
    subprocess.run(["import", "-window", "root", path], check=True, timeout=10)


def _detect_screenshot_backend():
    for name, is_available, capture_fn in config._SCREENSHOT_BACKENDS:
        try:
            if is_available():
                return name, capture_fn
        except Exception:
            continue
    return None, None

def _find_readable_file(name: str):
    name = name.strip().lower()
    if not name or not config.VOICE_FILES_DIR.is_dir():
        return None
    candidates = [
        p for p in config.VOICE_FILES_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in (".txt", ".md")
    ]
    best, best_score = None, -1
    for p in candidates:
        score = fuzz.token_sort_ratio(name, p.stem.lower())
        if score > best_score:
            best_score, best = score, p
    if best is not None and best_score >= 60:
        return best
    return None


def _capture_screen_ocr(lang: str = "rus+eng") -> str:
    if config._screenshot_capture_fn is None:
        return "__NO_SCREENSHOT_TOOL__"
    if shutil.which("tesseract") is None:
        return "__NO_TESSERACT__"

    with tempfile.TemporaryDirectory() as tmpdir:
        png_path = os.path.join(tmpdir, "screen.png")
        try:
            config._screenshot_capture_fn(png_path)
        except Exception as e:
            print(f"[screen] ошибка захвата экрана: {e}")
            return "__CAPTURE_FAILED__"
        if not os.path.exists(png_path):
            return "__CAPTURE_FAILED__"
        try:
            result = subprocess.run(
                ["tesseract", png_path, "stdout", "-l", lang],
                capture_output=True, text=True, timeout=20,
            )
            return result.stdout.strip()
        except Exception as e:
            print(f"[screen] ошибка tesseract: {e}")
            return "__OCR_FAILED__"


async def check_num(text: str) -> bool:
    if text.isdigit():
         return True
    for i in config.RU_NUMBERS_KEYS:
        isis, rate = await check_sim(text, i)
        if rate >= 90:
            return True
    return False


def parse_number(text: str) -> int:
    if text.isdigit():
         return int(text)
    words = text.lower().replace("-", " ").split()
    total = 0       
    current = 0    
    for word in words:
        if word not in config.RU_NUMBERS:
            continue 
        value = config.RU_NUMBERS[word]
        if word in config.MULTIPLIERS:
            current = current if current != 0 else 1
            total += current * value
            current = 0
        elif value >= 100:
            current += value
        else:
            current += value
    return total + current

def _transliterate_english_word(word: str) -> str:
    lower = word.lower()
    if lower in config._EN_LEXICON:
        return config._EN_LEXICON[lower]
    if word.isupper() and 2 <= len(word) <= 6:
        return " ".join(config._EN_LETTER_NAMES.get(ch.lower(), ch) for ch in word)
    result = lower
    for pattern, repl in config._EN_MULTI:
        result = result.replace(pattern, repl)
    result = "".join(config._EN_SINGLE.get(ch, ch) for ch in result)
    return result
 
 
def _number_to_words(num_str: str) -> str:
    num_str = num_str.replace(",", ".")
    try:
        if "." in num_str:
            return num2words(float(num_str), lang="ru")
        return num2words(int(num_str), lang="ru")
    except Exception:
        return " ".join(num2words(int(d), lang="ru") for d in num_str if d.isdigit())


def replace_numbers(text: str) -> str:
    if not text:
        return text
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<![\w.,])-(\d)", r"минус \1", text)
    text = re.sub(
        r"(\d+(?:[.,]\d+)?)\s*%",
        lambda m: _number_to_words(m.group(1)) + " процентов", text,
    )
    text = re.sub(
        r"\$\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*\$",
        lambda m: _number_to_words(m.group(1) or m.group(2)) + " долларов", text,
    )
    text = re.sub(
        r"€\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*€",
        lambda m: _number_to_words(m.group(1) or m.group(2)) + " евро", text,
    )
    text = re.sub(
        r"(\d+(?:[.,]\d+)?)\s*°\s*[CС]\b",
        lambda m: _number_to_words(m.group(1)) + " градусов Цельсия", text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(\d+(?:[.,]\d+)?)\s*°",
        lambda m: _number_to_words(m.group(1)) + " градусов", text,
    )
    text = re.sub(r"\d+(?:[.,]\d+)?", lambda m: _number_to_words(m.group()), text)

    text = config._EMOJI_RE.sub("", text)

    for sym, repl in config._SYMBOL_REPLACEMENTS.items():
        text = text.replace(sym, repl)
 
    text = re.sub(r"[A-Za-z]+", lambda m: _transliterate_english_word(m.group()), text)
 
    text = config._ALLOWED_CHARS_RE.sub(" ", text)
 
    text = re.sub(r"\s+", " ", text).strip()
 
    return text


def _heed_base_cmd():
    if shutil.which("heed"):
        return ["heed"]
    return [sys.executable, "-m", "heed.cli"]


def _run_heed(args, description):
    cmd = _heed_base_cmd() + args
    print(f"[heed] {description}: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd)
        return result.returncode == 0
    except FileNotFoundError:
        print(
            "[heed] команда 'heed' не найдена (даже как 'python -m heed.cli'). "
            "Проверьте, что пакет heed-wakeword установлен."
        )
        return False
    except Exception as e:
        print(f"[heed] ошибка при запуске ({description}): {e}")
        return False


def wget(url: str, dest: str, timeout: int = 30):
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=timeout) as resp, \
         open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)