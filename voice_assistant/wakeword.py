import asyncio
import json
import time
from pathlib import Path
import torch
import numpy as np
import onnxruntime as ort
import sounddevice as sd
from heed.audio import prepare_clip, log_mel

from voice_assistant import config 
from voice_assistant import audio 


class Detection:
    def __init__(self, name: str, confidence: float):
        self.name = name
        self.confidence = confidence

class HeedWakeWordListener:
    
    def __init__(self, export_dir: Path, name: str = "wake"):
        meta_path = export_dir / "wake.json"
        onnx_path = export_dir / "wake.onnx"

        self.name = name
        self.meta = json.loads(meta_path.read_text())
        self.session = ort.InferenceSession(str(onnx_path))
        self.input_name = self.session.get_inputs()[0].name

        self.threshold = self.meta["threshold"]
        self.consecutive_needed = self.meta.get("trigger", {}).get("consecutive_frames", 3)
        self.refractory_seconds = self.meta.get("trigger", {}).get("refractory_seconds", 1)

        self._buffer = np.empty(0, dtype=np.float32)
        self._new_samples = 0  

        self._consecutive = 0
        self._last_trigger_time = 0.0

        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue()
        self._loop = asyncio.get_event_loop()
        self._stream: sd.InputStream | None = None
    
    def reset(self):
        self._buffer = np.empty(0, dtype=np.float32)
        self._new_samples = 0
        self._consecutive = 0
    
        # Удаляем уже накопившийся звук
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
    def _audio_callback(self, indata, frames, time_info, status):
        if audio.is_speaking:
            return
        chunk = indata[:, 0].copy()
        self._loop.call_soon_threadsafe(self._queue.put_nowait, chunk)
    async def __aenter__(self):
        self._stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=int(config.SAMPLE_RATE * 0.02),  
            callback=self._audio_callback,
        )
        self._stream.start()
        return self

    async def __aexit__(self, *exc):
        if self._stream:
            self._stream.stop()
            self._stream.close()

    def _rms(self, x: np.ndarray) -> float:
        rms = np.sqrt(np.mean(x**2) + 1e-12)
        return 20.0 * np.log10(rms + 1e-12)

    def _run_inference(self) -> float:
        clip_tensor = torch.from_numpy(self._buffer).float()  
        clip = prepare_clip(clip_tensor)          
        mel = log_mel(clip).numpy()                 
        logit = self.session.run(None, {self.input_name: mel})[0][0]
        prob = 1.0 / (1.0 + np.exp(-logit))
        return float(prob)
    def _energy_gate_pass(self, x: np.ndarray) -> bool:
        eg = self.meta.get("energy_gate", {})
        rms_threshold_dbfs = eg.get("rms_threshold_dbfs", -55.0)
        voice_band_min_fraction = eg.get("voice_band_min_fraction", 0.15)
        lo_hz = eg.get("voice_band_lo_hz", 100.0)
        hi_hz = eg.get("voice_band_hi_hz", 7000.0)
    
        rms = np.sqrt(np.mean(x**2) + 1e-12)
        dbfs = 20.0 * np.log10(rms + 1e-12)
        if dbfs < rms_threshold_dbfs:
            return False
    
        windowed = x * np.hanning(len(x))
        spectrum = np.fft.rfft(windowed)
        power = np.abs(spectrum) ** 2
        freqs = np.fft.rfftfreq(len(x), d=1.0 / config.SAMPLE_RATE)
    
        total_power = power.sum() + 1e-12
        band_mask = (freqs >= lo_hz) & (freqs <= hi_hz)
        band_fraction = power[band_mask].sum() / total_power
    
        if band_fraction < voice_band_min_fraction:
            return False
    
        return True
    async def wait_for_detection(self) -> Detection:
        while True:
            chunk = await self._queue.get()

            self._buffer = np.concatenate([
                self._buffer,
                chunk
            ])
    
            if len(self._buffer) > config.WINDOW_SAMPLES:
                self._buffer = self._buffer[-config.WINDOW_SAMPLES:]
    
            self._new_samples += len(chunk)
    
            if len(self._buffer) < config.WINDOW_SAMPLES:
                continue
    
            if self._new_samples < config.HOP_SAMPLES:
                continue
    
            self._new_samples -= config.HOP_SAMPLES

            if not self._energy_gate_pass(self._buffer[-config.HOP_SAMPLES:]):
                self._consecutive = 0
                continue

            prob = self._run_inference()

            if prob > self.threshold:
                self._consecutive += 1
            else:
                self._consecutive = 0

            now = time.monotonic()
            if (
                self._consecutive >= self.consecutive_needed
                and now - self._last_trigger_time > self.refractory_seconds
            ):
                self._last_trigger_time = now
                self._consecutive = 0
                detection = Detection(self.name, prob)
                self.reset()
                return detection