import sherpa_onnx

from voice_assistant import config


class SpeechToText:
    def __init__(self, model_path: str = str(config.PROJECT_DIR / "sst_model/model.int8.onnx"),
                tokens_path : str = str(config.PROJECT_DIR / "sst_model/tokens.txt")):
        self.model_path = model_path
        self.tokens_path = tokens_path
        self.rec = sherpa_onnx.OfflineRecognizer.from_nemo_ctc(
            model=self.model_path,
            tokens=self.tokens_path,
            num_threads=1,
            sample_rate=16000
        )
