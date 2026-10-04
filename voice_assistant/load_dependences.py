import sys
import subprocess
import importlib
import shutil



_PIP_PACKAGE_NAMES = {
    "torch": "torch",
    "numpy": "numpy",
    "onnxruntime": "onnxruntime",
    "sounddevice": "sounddevice",
    "pymorphy3": "pymorphy3",
    "vosk": "vosk",
    "piper": "piper-tts",
    "sherpa_onnx": "sherpa-onnx",
    "rapidfuzz": "rapidfuzz",
    "llama_cpp": "llama-cpp-python",
    "silero": "silero",
    "num2words": "num2words",
    "heed": "heed-wakeword",
    "sentence_transformers": "sentence-transformers",
}


_LOCAL_ONLY_MODULES = []


def _pip_install(pip_name: str) -> bool:
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--upgrade", pip_name]
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"[deps] не удалось установить {pip_name}: {e}")
        return False


def ensure_dependencies():
    missing = []
    for module_name, pip_name in _PIP_PACKAGE_NAMES.items():
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing.append((module_name, pip_name))

    missing_local = []
    for module_name in _LOCAL_ONLY_MODULES:
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing_local.append(module_name)

    if missing:
        print(
            f"[deps] не найдено {len(missing)} пакет(ов), пробую установить: "
            + ", ".join(m for m, _ in missing)
        )
        still_missing = []
        for module_name, pip_name in missing:
            ok = _pip_install(pip_name)
            if ok:
                try:
                    importlib.import_module(module_name)
                except ImportError:
                    ok = False
            if not ok:
                still_missing.append(module_name)
        if still_missing:
            print(
                "[deps] не удалось автоматически установить: "
                + ", ".join(still_missing)
                + ". Установите их вручную и запустите скрипт заново."
            )

    if missing_local:
        print(
            "[deps] не найден(ы) локальный(е) модуль(и): "
            + ", ".join(missing_local)
            + ". Это не пакет(ы) PyPI — положите их рядом со скриптом "
              "(в той же папке/venv) вручную."
        )


