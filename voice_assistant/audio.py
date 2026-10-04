import asyncio
import time
import numpy as np
import sounddevice as sd
import re
from num2words import num2words
import unicodedata


from voice_assistant import config
from voice_assistant import utils
from voice_assistant import wakeword

is_speaking = False


def apply_metallic_effect(audio: np.ndarray, sample_rate: int, carrier_freq: float = 80.0, mix: float = 0.4) -> np.ndarray:
    """Кольцевая модуляция — классический 'металлический'/роботизированный эффект.
    carrier_freq: 50-150 Гц даёт грубый/роботизированный тембр, выше 150 — звонче, "жестяной".
    mix: 0 - эффекта нет, 1 - полностью модулированный сигнал."""
    t = np.arange(len(audio)) / sample_rate
    carrier = np.sin(2 * np.pi * carrier_freq * t)
    modulated = audio * carrier
    out = (1 - mix) * audio + mix * modulated
    peak = np.max(np.abs(out)) + 1e-9
    return (out / peak * np.max(np.abs(audio))).astype(np.float32)

def tovoice(model, text):
    global is_speaking
    is_speaking = True
    try:
        audio = model.apply_tts(
            text=text,
            speaker="eugene",
            sample_rate=24000,
        )
        audio_np = apply_metallic_effect(audio.numpy(), 24000, carrier_freq=60, mix=0.35)
        sd.play(audio_np, int(config.SAMPLE_RATE * config.SLOW_FACTOR))
        sd.wait()
    finally:
        time.sleep(0.25)
        is_speaking = False

async def reset_audio_state(listener, preroll_frames):
    await asyncio.sleep(0.1)
    while not listener._queue.empty():
        try:
            listener._queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    if preroll_frames is not None:
        preroll_frames.clear()
        

async def speak_interruptible(ttsmodel, text: str, listener: "wakeword.HeedWakeWordListener") -> bool:

    if not text.strip():
        return False

    tts_task = asyncio.create_task(utils.run_blocking(tovoice, ttsmodel, text))

    if not config.ENABLE_BARGE_IN:
        await tts_task
        return False

    barge_task = asyncio.create_task(listener.wait_for_detection())
    done, _pending = await asyncio.wait(
        {tts_task, barge_task}, return_when=asyncio.FIRST_COMPLETED
    )

    if barge_task in done:
        sd.stop() 
        await tts_task
        return True

    barge_task.cancel()
    try:
        await barge_task
    except asyncio.CancelledError:
        pass
    return False
