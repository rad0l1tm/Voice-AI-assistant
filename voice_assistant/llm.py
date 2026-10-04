import asyncio
import os
from llama_cpp import Llama
import threading

from voice_assistant import config


class QwenChat:
    def __init__(self, mod_path = None): 
        if (mod_path == None):
            mod_path = str(config.LLM_MODEL_FILE)
        self.llm = Llama(model_path=mod_path, n_ctx=4096,n_gpu_layers=0,n_threads=os.cpu_count() - 2,verbose=False)
        self.messages = []

    def add_system(self, text):
        
        self.messages.append({
            "role": "system",
            "content": text,
        })

    def ask(self, text):
        if len(self.messages) >= 1:
            system_message = self.messages[0]
            history = self.messages[1:]
            
            history = history[-10:]
            
            self.messages = [
                system_message,
                *history,
            ]
                
        self.messages.append({
            "role": "user",
            "content": text,
        })
        
        response = self.llm.create_chat_completion(messages=self.messages, max_tokens=256)

        self.messages.append({
            "role": "assistant",
            "content": response["choices"][0]["message"]["content"],
        })

        return response["choices"][0]["message"]["content"]

    async def ask_stream(self, text: str):
        if len(self.messages) >= 1:
            system_message = self.messages[0]
            history = self.messages[1:][-10:]
            self.messages = [system_message, *history]

        self.messages.append({"role": "user", "content": text})

        loop = asyncio.get_running_loop()
        out_queue: asyncio.Queue = asyncio.Queue()
        collected = []

        def _worker():
            try:
                stream = self.llm.create_chat_completion(
                    messages=self.messages, max_tokens=256, stream=True
                )
                for chunk in stream:
                    delta = chunk["choices"][0]["delta"].get("content")
                    if delta:
                        collected.append(delta)
                        loop.call_soon_threadsafe(out_queue.put_nowait, delta)
            except Exception as e:
                loop.call_soon_threadsafe(out_queue.put_nowait, ("__error__", str(e)))
            finally:
                loop.call_soon_threadsafe(out_queue.put_nowait, None)

        threading.Thread(target=_worker, daemon=True).start()

        buffer = ""
        while True:
            item = await out_queue.get()
            if item is None:
                break
            if isinstance(item, tuple):
                print(f"[llm] ошибка стрима: {item[1]}")
                break
            buffer += item
            match = config._SENTENCE_BOUNDARY_RE.search(buffer)
            while match:
                sentence = buffer[: match.start()].strip()
                buffer = buffer[match.end():]
                if sentence:
                    yield sentence
                match = config._SENTENCE_BOUNDARY_RE.search(buffer)

        tail = buffer.strip()
        if tail:
            yield tail

        full_response = "".join(collected).strip()
        self.messages.append({"role": "assistant", "content": full_response})