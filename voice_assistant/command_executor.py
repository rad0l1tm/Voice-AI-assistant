import json
from pathlib import Path
import os
from rapidfuzz import fuzz
import re
import subprocess
import glob
import configparser
import shlex
import random
import shutil
import tempfile

from voice_assistant import config
from voice_assistant import utils
from voice_assistant import audio


menu_process = None
opened_apps = {}
remembered_messages = {}

def open_menu(ttsmodel):
    apps = utils.get_installed_apps()
    if not apps:
        audio.tovoice(ttsmodel, "Приложения не найдены, сэр.")
        return

    try:
        with open(config.LAST_MENU_FILE, "w", encoding="utf-8") as f:
            json.dump(apps, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[warn] не удалось сохранить {config.LAST_MENU_FILE}: {e}")

    menu_text = "\n".join(f"{i + 1}. {name}" for i, (name, _) in enumerate(apps))

    launcher = next((c for c in config._LINUX_MENU_LAUNCHERS if shutil.which(c)), None)
    
    try:
        if launcher == "wofi":
            cmd = ["wofi", "--show", "dmenu", "--prompt", "Приложения", "--lines", "15"]
        elif launcher == "rofi":
            cmd = ["rofi", "-dmenu", "-p", "Приложения"]
        elif launcher == "bemenu":
            cmd = ["bemenu", "-p", "Приложения"]
        else:
            cmd = None

        if cmd:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            proc.stdin.write(menu_text.encode("utf-8"))
            proc.stdin.close()
            menu_process = proc
            audio.tovoice(ttsmodel, "Меню открыто.")
        elif shutil.which("zenity"):
            proc = subprocess.Popen(
                ["zenity", "--text-info", "--title=Приложения", "--width=400", "--height=500"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            proc.stdin.write(menu_text.encode("utf-8"))
            proc.stdin.close()
            menu_process = proc
            audio.tovoice(ttsmodel, "Меню открыто.")
        elif shutil.which("notify-send"):
            subprocess.Popen(
                ["notify-send", "-t", "0", "Меню приложений", menu_text],
                start_new_session=True,
            )
            menu_process = None
            audio.tovoice(ttsmodel, "Лаунчер не найден, список приложений показан уведомлением.")
        else:
            print(menu_text)
            menu_process = None
            audio.tovoice(ttsmodel, "Не нашёл ни одного лаунчера меню, список выведен в консоль.")
    except Exception as e:
        print(f"[error] _open_menu_linux: {e}")
        audio.tovoice(ttsmodel, "Не удалось открыть меню.")


def close_menu(ttsmodel):
    global menu_process
    closed = False
    if menu_process is not None and menu_process.poll() is None:
        try:
            menu_process.terminate()
            closed = True
        except Exception:
            pass
    menu_process = None

    try:
        result = subprocess.run(["pkill", "-x", "wofi"], check=False)
        if result.returncode == 0:
            closed = True
    except FileNotFoundError:
        pass
    try:
        subprocess.run(["pkill", "-x", "notify-send"], check=False)
    except FileNotFoundError:
        pass

    audio.tovoice(ttsmodel, "Меню закрыто, сэр" if closed else "Открытое меню не найдено сэр")




def remember_app(number_word: str, app_name: str, ttsmodel):
    number = utils.parse_number(number_word)
    if not os.path.exists(config.LAST_MENU_FILE):
        audio.tovoice(ttsmodel, "сэр, сначала откройте меню командой  Открой меню")
        return

    try:
        with open(config.LAST_MENU_FILE, "r", encoding="utf-8") as f:
            apps = json.load(f)
    except Exception:
        audio.tovoice(ttsmodel, "Не удалось прочитать список меню, сэр")
        return

    if number is None or number < 1 or number > len(apps):
        audio.tovoice(ttsmodel, "Не удалось распознать номер приложения, сэр")
        return
    app_display_name, exec_cmd = apps[number - 1]
    app_name = app_name.strip()
    if not app_name:
        audio.tovoice(ttsmodel, "Не расслышал имя для приложения, сэр")
        return
    known = utils.load_known_apps()
    known[app_name.lower()] = {"exec": exec_cmd, "display_name": app_display_name}
    utils.save_known_apps(known)

    audio.tovoice(ttsmodel, f"Запомнил приложение {app_name} с номером {number_word}.")


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# async def read_file_range(command_text: str, ttsmodel, listener):
#     match = config._FILE_READ_RE.match(command_text.strip())
#     if not match:
#         await utils.run_blocking(
#             audio.tovoice, ttsmodel,
#             "Не понял, какой файл и какие строки читать, сэр. Скажите, "
#             "например: прочитай файл заметки от пяти до десяти.",
#         )
#         return

#     raw_name, from_word, to_word = match.groups()
#     start = utils.parse_number(from_word.strip())
#     end = utils.parse_number(to_word.strip())
#     if not start or not end:
#         await utils.run_blocking(audio.tovoice, ttsmodel, "Не расслышал номера строк, сэр.")
#         return
#     if start > end:
#         start, end = end, start

#     path = await utils.run_blocking(utils._find_readable_file, raw_name)
#     if path is None:
#         await utils.run_blocking(audio.tovoice, ttsmodel, f"Не нашёл файл {raw_name}, сэр.")
#         return

#     try:
#         with open(path, "r", encoding="utf-8", errors="ignore") as f:
#             lines = f.readlines()
#     except Exception as e:
#         print(f"[file] ошибка чтения {path}: {e}")
#         await utils.run_blocking(audio.tovoice, ttsmodel, "Не удалось прочитать файл, сэр.")
#         return

#     start_idx = max(1, start) - 1
#     end_idx = min(len(lines), end)
#     if start_idx >= end_idx:
#         await utils.run_blocking(audio.tovoice, ttsmodel, "Указанный диапазон строк пуст, сэр.")
#         return

#     chunk_text = "".join(lines[start_idx:end_idx]).strip()
#     if not chunk_text:
#         await utils.run_blocking(audio.tovoice, ttsmodel, "В этом диапазоне строк ничего нет, сэр.")
#         return

#     await utils.run_blocking(audio.tovoice, ttsmodel, f"Читаю {path.name}, строки {start} - {end}.")

#     for sentence in config._SENTENCE_BOUNDARY_RE.split(chunk_text):
#         sentence = sentence.strip()
#         if not sentence:
#             continue
#         if await audio.speak_interruptible(ttsmodel, utils.replace_numbers(sentence), listener):
#             break


async def open_app(app_name: str, ttsmodel):
    app_name = app_name.strip()
    known = utils.load_known_apps()
    if not app_name or not known:
        await utils.run_blocking(audio.tovoice, ttsmodel, "Приложение не найдено, сэр")
        return

    best_key = None
    best_score = -1
    for key in known:
        _, score = await utils.check_sim(app_name, key, thr=0)
        if score > best_score:
            best_score = score
            best_key = key

    if best_key is None or best_score < 70:
        await utils.run_blocking(audio.tovoice, ttsmodel, "Приложение не найдено, сэр")
        return
    exec_cmd = known[best_key]["exec"]
    display_name = known[best_key].get("display_name", best_key)
    try:
        args = shlex.split(exec_cmd)
        opened_apps[best_key] = subprocess.Popen(
            args,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await utils.run_blocking(audio.tovoice, ttsmodel, f"Открываю {display_name}.")
    except Exception as e:
        print(f"[error] open_app: {e}")
        await utils.run_blocking(audio.tovoice, ttsmodel, "Не удалось запустить приложение, сэр")


async def close_app(app_name: str, ttsmodel):
    global opened_apps
    bestrate = 0
    bestname = "None"
    for key in opened_apps:
        isis, rate = await utils.check_sim(app_name, key)
        if isis and bestrate < rate:
            bestrate = rate
            bestname = key
    if bestrate < 70:
        audio.tovoice(ttsmodel, f"Приложение {app_name} не найдено, сэр")
        return
    app_name = bestname
    app_proc = opened_apps.get(app_name, None)
    
    if app_proc is not None and app_proc.poll() is None:
        opened_apps.pop(app_name, [])
        try:
            app_proc.terminate()
            try:
                app_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                app_proc.kill()
        except Exception:
            audio.tovoice(ttsmodel, "Не могу закрыть приложение, сэр")
        app_proc = None
    else: 
        audio.tovoice(ttsmodel, f"Приложение {app_name} не найдено, сэр")
        return
    audio.tovoice(ttsmodel, f"Приложение {app_name} закрыто, сэр.")

    
async def list_apps(ttsmodel):
    global opened_apps
    allapps = ""
    for key in opened_apps:
        print(opened_apps[key].pid)
        allapps += f", {key}"
    if len(allapps) == 0:
        audio.tovoice(ttsmodel, "Открытых мною приложений нет, сэр.")
    else:
        audio.tovoice(ttsmodel, allapps)


async def read_screen_command(ttsmodel, qwenny, listener, summarize: bool, question: str):
    ocr_text = await utils.run_blocking(utils._capture_screen_ocr)

    if ocr_text == "__NO_SCREENSHOT_TOOL__":
        await utils.run_blocking(
            audio.tovoice, ttsmodel,
            "Не нашёл инструмент для скриншота, сэр. Нужен grim, scrot или imagemagick.",
        )
        return
    if ocr_text == "__NO_TESSERACT__":
        await utils.run_blocking(audio.tovoice, ttsmodel, "Для чтения экрана нужен tesseract, сэр.")
        return
    if ocr_text in ("__CAPTURE_FAILED__", "__OCR_FAILED__") or not ocr_text.strip():
        await utils.run_blocking(audio.tovoice, ttsmodel, "Не удалось распознать текст на экране, сэр.")
        return

    if not summarize:
        prompt = (
            "Ответь на вопросы по тексту.\n\nТекст:\n"
            f"{ocr_text}"
            f"\n\nВопрос: \n{question}"
        )
        async for sentence in qwenny.ask_stream(prompt):
            sentence_g = utils.replace_numbers(sentence)
            if sentence_g.strip():
                if await audio.speak_interruptible(ttsmodel, sentence_g, listener):
                    break
        # for sentence in _SENTENCE_BOUNDARY_RE.split(ocr_text):
        #     sentence = sentence.strip()
        #     if not sentence:
        #         continue
        #     if await audio.speak_interruptible(ttsmodel, replace_numbers(sentence), listener):
        #         break
        # return
        return

    prompt = (
        f"На экране написано следующее:\n{ocr_text}\n\n"
        "Кратко перескажи содержимое своими словами."
    )
    async for sentence in qwenny.ask_stream(prompt):
        print(sentence)

        sentence_g = utils.replace_numbers(sentence)
        if sentence_g.strip():
            if await audio.speak_interruptible(ttsmodel, sentence_g, listener):
                break

    
async def process_commands(command_text: str, ttsmodel, qwenny, listener, classifier):
    global is_qwenny
    segments = re.split(r"\s+и\s+|[,;]", command_text)
    segments = [s.strip() for s in segments if s.strip()]
    if not segments:
        return

    for segment in segments:
        words = segment.split()
        if not words:
            continue

        matched, _ = await utils.check_sim(" ".join(words[:2]), "открой меню")
        if matched and _ == 100:
            open_menu(ttsmodel)
            continue

        matched, _ = await utils.check_sim(" ".join(words[:2]), "закрой меню")
        if matched and _ == 100:
            close_menu(ttsmodel)
            continue

        matched, _ = await utils.check_sim(" ".join(words[:2]), "запомни номер")
        if matched and len(words) >= 4:
            last_num = 3
            while (last_num< len(words) and await utils.check_num(words[last_num])):
                last_num += 1
            number_word = " ".join(words[2:last_num])
            app_name = " ".join(words[last_num:])
            remember_app(number_word, app_name, ttsmodel)
            continue

        # matched, _ = await utils.check_sim(" ".join(words[:2]), "прочитай файл")
        # if matched and _ >= 85:
        #     rest = " ".join(words[2:])
        #     await utils.read_file_range(rest, ttsmodel, listener)
        #     continue

        matched, _ = await utils.check_sim(" ".join(words[:3]), "что на экране")
        if matched and _ >= 85:
            await read_screen_command(ttsmodel, qwenny, listener, True, "")
            continue

        matched, _ = await utils.check_sim(" ".join(words[:2]), "видишь экран")
        if matched and _ >= 85:
            await read_screen_command(ttsmodel, qwenny, listener, False, " ".join(words[2:]))
            
            continue
            
        matched, _ = await utils.check_sim(words[0], "открой", thr=80)
        if matched and len(words) >= 2:
            app_name = " ".join(words[1:])
            await open_app(app_name, ttsmodel)
            continue

        matched, _ = await utils.check_sim(words[0], "закрой", thr=80)
        if matched and len(words) >= 2:
            app_name = " ".join(words[1:])
            await close_app(app_name, ttsmodel)
            continue
    
        matched, _ = await utils.check_sim(" ".join(words[:2]), "начни диалог")
        if matched and _ == 100:
            is_qwenny = True
            audio.tovoice(ttsmodel, random.choice(["Спрашивайте, сэр.", "К вашим услугам, сэр."]))
            continue
            
        matched, _ = await utils.check_sim(" ".join(words[:2]), "заверши диалог")
        if matched and _ == 100:
            audio.tovoice(ttsmodel, "Диалог завершен, сэр.")
            is_qwenny = False
            continue

        matched, _ = await utils.check_sim(" ".join(words[:4]), "перечисли приложения")
        if matched and _ >= 90:
            await list_apps(ttsmodel)
            continue

        print(f"[jarvis] команда не распознана: {segment!r}")
        audio.tovoice(ttsmodel, "Повторите команду, сэр.")

# async def process_commands(command_text: str, ttsmodel, qwenny, listener, classifier):
#     global is_qwenny
#     segments = re.split(r"\s+и\s+|[,;]", command_text)
#     segments = [s.strip() for s in segments if s.strip()]
#     if not segments:
#         return
    
#     for segment in segments:
#         words = segment.split()
#         if not words:
#             continue
#         pred = classifier.predict([" ".join(words[:i]) for i in range(1, 5)])
#         if (pred[1][0] == "открой меню" and pred[1][1] >= 0.9) or (pred[3][0] == "открой меню" and pred[3][1] >= 0.9):
#             open_menu(ttsmodel)
#             continue
            
#         if pred[1][0] == "закрой меню" and pred[1][1] >= 0.9:
#             close_menu(ttsmodel)
#             continue

#         if pred[1][0] == "запомни номер" and pred[1][1] >= 0.9 and len(words) >= 4:
#             last_num = 3
#             while (last_num< len(words) and await utils.check_num(words[last_num])):
#                 last_num += 1
#             number_word = " ".join(words[2:last_num])
#             app_name = " ".join(words[last_num:])
#             remember_app(number_word, app_name, ttsmodel)
#             continue
#         if pred[2][0] == "запомни номер" and pred[2][1] >= 0.9 and len(words) >= 5:
#             last_num = 4
#             while (last_num< len(words) and await utils.check_num(words[last_num])):
#                 last_num += 1
#             number_word = " ".join(words[3:last_num])
#             app_name = " ".join(words[last_num:])
#             remember_app(number_word, app_name, ttsmodel)
#             continue
#         if pred[3][0] == "запомни номер" and pred[3][1] >= 0.9 and len(words) >= 6:
#             last_num = 5
#             while (last_num< len(words) and await utils.check_num(words[last_num])):
#                 last_num += 1
#             number_word = " ".join(words[4:last_num])
#             app_name = " ".join(words[last_num:])
#             remember_app(number_word, app_name, ttsmodel)
#             continue
#         # matched, _ = await utils.check_sim(" ".join(words[:2]), "прочитай файл")
#         # if matched and _ >= 85:
#         #     rest = " ".join(words[2:])
#         #     await utils.read_file_range(rest, ttsmodel, listener)
#         #     continue

#         if pred[2][0] == "что на экране" and pred[2][1] >= 0.8:
#             await read_screen_command(ttsmodel, qwenny, listener, True, "")
#             continue

#         if pred[1][0] == "видишь экран" and pred[1][1] >= 0.8:
#             await read_screen_command(ttsmodel, qwenny, listener, False, " ".join(words[2:]))
#             continue
#         if pred[2][0] == "видишь экран" and pred[2][1] >= 0.8:
#             await read_screen_command(ttsmodel, qwenny, listener, False, " ".join(words[3:]))
#             continue
#         if pred[3][0] == "видишь экран" and pred[3][1] >= 0.8:
#             await read_screen_command(ttsmodel, qwenny, listener, False, " ".join(words[4:]))
#             continue
            
#         if pred[0][0] == "открой" and pred[0][1] >= 0.8 and len(words) >= 2:
#             app_name = " ".join(words[1:])
#             await open_app(app_name, ttsmodel)
#             continue

#         if pred[0][0] == "закрой" and pred[0][1] >= 0.8 and len(words) >= 2:
#             app_name = " ".join(words[1:])
#             await close_app(app_name, ttsmodel)
#             continue
    
#         if pred[1][0] == "начни диалог" and pred[1][1] >= 0.8:
#             is_qwenny = True
#             audio.tovoice(ttsmodel, random.choice(["Спрашивайте, сэр.", "К вашим услугам, сэр."]))
#             continue
            
#         if pred[1][0] == "заверши диалог" and pred[1][1] >= 0.8:
#             audio.tovoice(ttsmodel, "Диалог завершен, сэр.")
#             is_qwenny = False
#             continue

#         if pred[3][0] == "перечисли приложения" and pred[3][1] >= 0.8:
#             await list_apps(ttsmodel)
#             continue

#         print(f"[jarvis] команда не распознана: {segment!r}")
#         audio.tovoice(ttsmodel, "Повторите команду, сэр.")
