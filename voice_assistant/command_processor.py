from sentence_transformers import SentenceTransformer
import numpy as np

from voice_assistant import config

# class CommandClassifier:
#     def __init__(self):
#         self.model = SentenceTransformer("cointegrated/rubert-tiny2")
#         self.labels = []
#         self.embeddings = []
#         for label, phrases in config.COMMAND_EXAMPLES.items():
#             embs = self.model.encode(phrases, normalize_embeddings=True)
#             self.labels.append(label)
#             self.embeddings.append(embs.mean(axis=0))

#         self.embeddings = np.stack(self.embeddings)

#     def predict(self, texts: list, threshold: float = 0.5):
#         embs = self.model.encode(texts, normalize_embeddings=True)
#         sims = embs @ self.embeddings.T
#         best = int(np.argmax(sims))
#         results = []
#         for i in range(len(texts)):
#             best = np.argmax(sims[i])
#             score = sims[i, best]
#             print(f"Similarity is {score} for {self.labels[best]} ")
#             results.append((
#                 self.labels[best],
#                 float(score),
#             ))
    
#         return results


CONFUSABLE_PAIRS = {
    frozenset({"начни диалог", "заверши диалог"}): {
        "начни диалог": {"начни", "давай", "поговорим", "вопрос", "начать"},
        "заверши диалог": {"заверши", "закончи", "хватит", "пока", "стоп", "завершить"},
    },
    frozenset({"открой меню", "закрой меню"}): {
        "открой меню": {"открой", "открывай", "покажи", "взгляну"},
        "закрой меню": {"закрой", "убери", "сверни"},
    },
    frozenset({"открой", "закрой"}): {
        "открой": {"открой", "запусти"},
        "закрой": {"закрой", "сверни", "убери"},
    },
}


class CommandClassifier:
    def __init__(self):
        self.model = SentenceTransformer("cointegrated/rubert-tiny2")
        self.labels, self.embeddings = [], []
        for label, phrases in config.COMMAND_EXAMPLES.items():
            embs = self.model.encode(phrases, normalize_embeddings=True)
            for emb in embs:
                self.labels.append(label)
                self.embeddings.append(emb)
        self.embeddings = np.stack(self.embeddings)

    def _tiebreak(self, text, label_a, label_b):
        rules = CONFUSABLE_PAIRS.get(frozenset({label_a, label_b}))
        if rules is None:
            return None
        words = set(text.lower().split())
        hits_a = len(words & rules.get(label_a, set()))
        hits_b = len(words & rules.get(label_b, set()))
        if hits_a > hits_b:
            return label_a
        if hits_b > hits_a:
            return label_b
        return None

    def predict(self, texts: list, threshold: float = 0.5, margin: float = 0.03):
        embs = self.model.encode(texts, normalize_embeddings=True)
        sims = embs @ self.embeddings.T
        results = []
        for i, text in enumerate(texts):
            order = np.argsort(sims[i])[::-1]
            best_i, second_i = int(order[0]), int(order[1])
            best_score, second_score = float(sims[i, best_i]), float(sims[i, second_i])
            label, second_label = self.labels[best_i], self.labels[second_i]

            if best_score < threshold:
                label = "unknown"
            elif label != second_label and (best_score - second_score) < margin:
                resolved = self._tiebreak(text, label, second_label)
                if resolved is not None:
                    label = resolved

            print(f"'{text}' -> {best_score:.4f} (2й: {second_label} {second_score:.4f}) -> {label}")
            results.append((label, best_score))
        return results