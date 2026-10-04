import asyncio
from pathlib import Path
import sys
import pymorphy3
import shutil
import argparse
import silero_vad

from voice_assistant import config 
from voice_assistant import command_executor
from voice_assistant import utils 
from voice_assistant import preload 
from voice_assistant import stt 
from voice_assistant import wakeword 
from voice_assistant import assistant 
from voice_assistant import load_dependences

async def main():
    parser = argparse.ArgumentParser(description="Голосовой ассистент")
    parser.add_argument("--llm-model", help="Путь к llm-модели", default = config.PROJECT_DIR / "Qwen3.5-4B-Q4_K_M.gguf")
    parser.add_argument("--stt-model", help="Путь к stt-модели", default = config.PROJECT_DIR / "stt_model")
    parser.add_argument("--vad-model", help="Путь к vad-модели", default = str(Path(silero_vad.__file__).parent / 'data' / 'silero_vad.onnx'))
    parser.add_argument("--load-dependences", action="store_true", help="Автоматически скачать зависимости.")
    args = parser.parse_args()  
    if args.load_dependences:
        load_dependences.ensure_dependencies()
    config.SCREENSHOT_BACKEND_NAME, config._screenshot_capture_fn = utils._detect_screenshot_backend()
    config.LLM_MODEL_FILE = Path.cwd() / args.llm_model
    print(config.LLM_MODEL_FILE)
    if config.SCREENSHOT_BACKEND_NAME:
        print(f"[screen] захват экрана включён, инструмент: {config.SCREENSHOT_BACKEND_NAME}")
    else:
        print(
            "[screen] не нашёл ни grim, ни scrot, ни import (ImageMagick) — "
            "команды 'что на экране'/'прочитай экран' работать не будут. "
            "Поставьте один из них, например: sudo apt install grim"
        )
    
    if shutil.which("tesseract") is None:
        print(
            "[screen] tesseract не найден — команды чтения экрана работать не "
            "будут, даже если скриншот сделать получится. Поставьте: "
            "sudo apt install tesseract-ocr tesseract-ocr-rus"
        )
    config.STT_MODEL_DIR = Path(args.stt_model)
    sst_model_ready, stt_model_path, stt_tokens_path = await utils.run_blocking(preload.ensure_stt_model, config.STT_MODEL_DIR)
    if not sst_model_ready:
        print("Не удалось подготовить Speech-to-text модель. Завершаю работу.")
    ww_model_ready = await utils.run_blocking(preload.ensure_wakeword_model, config.EXPORT_DIR, config.keyphr.get("simj"))
    if not ww_model_ready:
        print(
            "[heed] Не удалось подготовить wake-word модель — "
            "ассистент не может запуститься без неё. Завершаю работу."
        )
        return
    stt_ = stt.SpeechToText(stt_model_path, stt_tokens_path) 
    #morph = pymorphy3.MorphAnalyzer()
    isawaken = False
    async with wakeword.HeedWakeWordListener(config.EXPORT_DIR, name="my_phrase") as listener:
        print("Listening for wake word... Press Ctrl+C to stop.\n")
        while True:
            if not isawaken:
                await listener.wait_for_detection()
                break
        assistant.listener = listener
        await assistant.listen_and_transcribe(listener, stt_, config.COMMAND_LISTEN_SECONDS, args.vad_model)


if __name__ == "__main__":
    asyncio.run(main())