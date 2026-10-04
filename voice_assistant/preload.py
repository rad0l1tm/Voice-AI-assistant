import time
from pathlib import Path
import sys
import sounddevice as sd
from silero import silero_tts
import subprocess
import shutil
import tarfile
import urllib

from voice_assistant import config
from voice_assistant import utils
from voice_assistant import audio

def pretovoice(model, text):
    try:
        audio = model.apply_tts(
            text=text,
            speaker="aidar",
            sample_rate=24000,
        )
        sd.play(audio.numpy(), 24000)
        sd.wait()
    finally:
        time.sleep(0.25)

def ensure_wakeword_model(
    export_dir: Path,
    phrase: str = None,
    positive_count: int = 15,
    negative_count: int = 15,
) -> bool:
    """
    Проверяет, есть ли уже обученная wake-word модель (wake.onnx + wake.json
    в export_dir). Если нет — проводит процесс записи и обучения прямо через
    CLI heed-wakeword: init -> record (positive) -> record (negative) ->
    train -> export. Требует интерактивного терминала и микрофона (запись
    идёт вживую), поэтому вызывается один раз, до старта основного цикла.
    """
    wake_onnx = export_dir / "wake.onnx"
    wake_json = export_dir / "wake.json"
    if wake_onnx.exists() and wake_json.exists():
        return True

    project_name = export_dir.parent.name or "wakeword"
    prettsmodel, example_text = silero_tts(
        language="ru",
        speaker="v5_ru",
    )
    pretovoice(prettsmodel, "Модель обнаружения ключефого слова не найдена. Запускаю запись и обучение.")
    print("=" * 70)
    print("Wake-word модель не найдена (" + str(export_dir) + ").")
    print("Запускаю запись и обучение через heed-wakeword.")
    print("=" * 70)

    if not phrase:
        pretovoice(prettsmodel, "Введите ключевую фразу для пробуждения ассистента.")
        phrase = input(
            "Введите ключевую фразу для пробуждения ассистента "
            f"(Enter — по умолчанию {config.keyphr.get('simj', 'ассистент')!r}): "
        ).strip() or config.keyphr.get("simj", "ассистент")

    if not utils._run_heed(
        ["init", project_name, "--phrase", phrase],
        f"создаю проект '{project_name}' с фразой {phrase!r}",
    ):
        pretovoice(prettsmodel, "не удалось создать проект, настройка модели прервана.")
        print("[heed] не удалось создать проект, настройка модели прервана.")
        return False
    pretovoice(prettsmodel, "Сейчас будет запись положительных образцов. чётко произносите фразу в микрофон, меняя интонацию, громкость и расстояние до микрофона. Нажмите Enter, чтобы начать.")
    input(
        f"\nСейчас будет запись {positive_count} положительных образцов — "
        f"чётко произносите фразу {phrase!r} в микрофон, меняя интонацию, "
        "громкость и расстояние до микрофона. Нажмите Enter, чтобы начать..."
    )
    if not utils._run_heed(
        ["record", project_name, "--kind", "positive", "--count", str(positive_count)],
        "записываю положительные образцы",
    ):
        print("[heed] запись положительных образцов не удалась.")
        return False
    pretovoice(prettsmodel, "Теперь запись отрицательных образцов. произносите другие слова и фразы, то есть НЕ ключевую фразу и похожие по звучанию. Нажмите Enter, чтобы начать...")
    input(
        f"\nТеперь запись {negative_count} отрицательных образцов — "
        "произносите другие слова и фразы (НЕ ключевую фразу), в том числе "
        "похожие по звучанию. Нажмите Enter, чтобы начать..."
    )
    if not utils._run_heed(
        ["record", project_name, "--kind", "negative", "--count", str(negative_count)],
        "записываю отрицательные образцы",
    ):
        print("[heed] запись отрицательных образцов не удалась.")
        return False
    pretovoice(prettsmodel, "Обучаю модель (от нескольких секунд до пары минут)...")
    print("\nОбучаю модель (от нескольких секунд до пары минут)...")
    if not utils._run_heed(["train", project_name], "обучаю модель"):
        print("[heed] обучение не удалось.")
        return False
    pretovoice(prettsmodel, "Экспортирую модель...")
    print("Экспортирую модель...")
    if not utils._run_heed(["export", project_name], "экспортирую модель"):
        pretovoice(prettsmodel, "экспорт не удался.")
        print("[heed] экспорт не удался.")
        return False

    if wake_onnx.exists() and wake_json.exists():
        print(f"[heed] wake-word модель готова: {export_dir}")
        return True
    pretovoice(prettsmodel, "экспорт завершился, но файлы не найдены по пути. Проверьте вручную имя проекта и путь экспорта.")
    print(
        f"[heed] экспорт завершился, но файлы не найдены по пути {export_dir}. "
        "Проверьте вручную имя проекта и путь экспорта."
    )
    return False


def ensure_stt_model(sttdir: Path):
    model_path = ""
    token_path = ""
    if not sttdir.exists():
        Path(config.PROJECT_DIR + "/stt_model").mkdir(exist_ok=True)
        utils.wget("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-ctc-giga-am-v2-russian-2025-04-19.tar.bz2", 
             config.PROJECT_DIR + "/stt_model/sherpa-onnx-nemo-ctc-giga-am-v2-russian-2025-04-19.tar.bz2")
        with tarfile.open(config.PROJECT_DIR + "/stt_model/sherpa-onnx-nemo-ctc-giga-am-v2-russian-2025-04-19.tar.bz2", "r:bz2") as tar:
            tar.extractall("./stt_model/")
        #os.remove("./stt_model/sherpa-onnx-nemo-ctc-giga-am-v2-russian-2025-04-19.tar.bz2")
        model_path = config.PROJECT_DIR + "/stt_model/sherpa-onnx-nemo-ctc-giga-am-v2-russian-2025-04-19/model.int8.onnx"
        token_path = config.PROJECT_DIR + "/stt_model/sherpa-onnx-nemo-ctc-giga-am-v2-russian-2025-04-19/tokens.txt"
    else:
        model_list = list(sttdir.rglob("*.onnx"))
        token_list = list(sttdir.rglob("tokens.txt"))
        if len(model_list) == 0:
            print("STT модель не найдена.")
            return False, "", ""
        if len(token_list) == 0:
            print("Токены STT модели не найдены")
            return False, "", ""
        model_path = str(model_list[0])
        token_path = str(token_list[0])
    return True, model_path, token_path
