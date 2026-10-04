import asyncio
import numpy as np
import sounddevice as sd
import sherpa_onnx
from silero import silero_tts
from collections import deque
import random

from voice_assistant import wakeword
from voice_assistant import config
from voice_assistant import utils
from voice_assistant import audio
from voice_assistant import llm 
from voice_assistant import command_executor
from voice_assistant import stt 
from voice_assistant import command_processor

is_qwenny = False

async def listen_and_transcribe(
    listener: "wakeword.HeedWakeWordListener",
    stt: stt.SpeechToText,
    duration_seconds: float,
    vad: str
) -> str:
    MAX_SEGMENTS_PER_BATCH = 8
    STUCK_REPEAT_THRESHOLD = 3 
    vad_config = sherpa_onnx.VadModelConfig()
    vad_config.silero_vad.model = vad
    vad_config.silero_vad.threshold = 0.4
    vad_config.silero_vad.min_silence_duration = 1.25 
    vad_config.silero_vad.min_speech_duration = 0.1  
    vad_config.sample_rate = 16000
    vad = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=30)
    
    ttsmodel, example_text = silero_tts(
        language="ru",
        speaker="v5_ru",
    )
    print("Здравствуйте, "+("сэр." if config.SEX=='male' else "мэм."))
    await utils.run_blocking(audio.tovoice, ttsmodel, random.choice(["Здравствуйте, "+("сээр." if config.SEX=='male' else "мээм."), "Приветствую, "+("сээр." if config.SEX=='male' else "мээм.")]) + "Прошу немного подождать - я подготавливаю данные.")
    qwenny = llm.QwenChat()
    qwenny.add_system(config.keyphr["scs"])
    command_classifier = command_processor.CommandClassifier()
    await utils.run_blocking(audio.tovoice, ttsmodel, "Данные готовы к работе, "+("сэр." if config.SEX=='male' else "мэм."))

    while not listener._queue.empty():
        try:
            listener._queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    nnn = 1
    preroll_frames = deque(maxlen=int(config.SAMPLE_RATE * 0.4 / 320))
    await audio.reset_audio_state(listener, preroll_frames)

    while True:
        chunk = await listener._queue.get()
    
        if chunk.size == 0 or not np.isfinite(chunk).all() or not chunk.any():
            continue
    
        preroll_frames.append(chunk)
        vad.accept_waveform(chunk)
    
        segments_this_batch = 0
        stuck_counter = 0
        last_len = -1
    
        while not vad.empty():
            if segments_this_batch >= MAX_SEGMENTS_PER_BATCH:
                print("[warn] too many segments per batch, recreating VAD")
                vad = make_vad()
                break
            segments_this_batch += 1
    
            segment = vad.front
            audio_segment = np.array(segment.samples, dtype=np.float32, copy=True)
            vad.pop()
    
            if len(audio_segment) == last_len:
                stuck_counter += 1
                if stuck_counter >= STUCK_REPEAT_THRESHOLD:
                    print("[warn] VAD stuck on identical segments, recreating")
                    vad = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=30)
                    last_len = -1
                    stuck_counter = 0
                    break
            else:
                last_len = len(audio_segment)
                stuck_counter = 0
    
            nnn += 1
            print(f"segment samples: {len(audio_segment)}, dur={len(audio_segment)/16000:.2f}s")
    
            if preroll_frames:
                preroll_audio = np.concatenate(list(preroll_frames))
                pad = int(config.SAMPLE_RATE * 0.2)
                if len(preroll_audio) >= pad:
                    audio_segment = np.concatenate([preroll_audio[-pad:], audio_segment])
    
            stream = stt.rec.create_stream()
            stream.accept_waveform(config.SAMPLE_RATE, audio_segment)
            stt.rec.decode_stream(stream)
            text = stream.result.text.strip()
    
            if not text:
                continue
    
            print(text)
            isend, _ = await utils.check_sim(text, config.keyphr["stdn"])
            if isend:
                await utils.run_blocking(audio.tovoice, ttsmodel, "До свидания, "+("сэр." if config.SEX=='male' else "мэм.")+"!")
                return ""

            words_in_text = text.split()
            first_word = words_in_text[0] if words_in_text else ""
            is_command, _ = await utils.check_sim(first_word, config.keyphr["simj"], thr=65)
            if not is_qwenny or is_command:
                if _ == 100:
                    command_text = " ".join(words_in_text[1:])
                else: 
                    command_text = " ".join(words_in_text)
                if command_text.strip():
                    await command_executor.process_commands(command_text, ttsmodel, qwenny, listener, command_classifier)
                else:
                    await utils.run_blocking(audio.tovoice, ttsmodel, random.choice(["Слушаю, "+("сэр." if config.SEX=='male' else "мэм."), "Да, "+("сэр." if config.SEX=='male' else "мэм.")]))

                await audio.reset_audio_state(listener, preroll_frames)
                vad = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=30)
                break

            if (is_qwenny):
                response = qwenny.ask(text)
                response_g = utils.replace_numbers(response)
                print(qwenny.messages[-1])
    
                await utils.run_blocking(audio.tovoice, ttsmodel, response_g)
            else:
                await utils.run_blocking(audio.tovoice, ttsmodel, random.choice(["Не расслышал вас, "+("сэр." if config.SEX=='male' else "мэм."), "Не понял вас, "+("сэр." if config.SEX=='male' else "мэм.")]))

            await audio.reset_audio_state(listener, preroll_frames)
            vad = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=30)
    
            break