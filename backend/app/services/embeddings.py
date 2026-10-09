"""all-MiniLM-L6-v2 向量服务（懒加载 + 进程内单例）。"""

from __future__ import annotations

import threading
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import get_settings

if TYPE_CHECKING:
    from numpy.typing import NDArray


class EmbeddingService:
    """把文本编码成向量，并计算余弦相似度。

    模型在第一次真正用到时才加载，避免服务启动就阻塞在权重下载上。
    ``SentenceTransformer.encode`` 是 CPU 密集操作，调用方应放到线程池里执行。
    """

    def __init__(self, model_name: str, device: str = "cpu", normalize: bool = True) -> None:
        self.model_name = model_name
        self.device = device
        self.normalize = normalize
        self._model: SentenceTransformer | None = None
        self._lock = threading.Lock()

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    self._model = SentenceTransformer(self.model_name, device=self.device)
        return self._model

    @property
    def dimension(self) -> int:
        model = self.model
        # sentence-transformers >= 6 重命名了该方法，这里兼容新旧版本。
        get_dimension = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
        return int(get_dimension())

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self.model.encode(
            texts,
            normalize_embeddings=self.normalize,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32).tolist()

    def similarity(self, source: str, targets: list[str]) -> list[tuple[int, str, float]]:
        """返回按相似度降序排列的 ``(原始下标, 文本, 分数)``。"""
        if not targets:
            return []

        vectors = np.asarray(self.encode([source, *targets]), dtype=np.float32)
        source_vector: NDArray[np.float32] = vectors[0]
        target_vectors: NDArray[np.float32] = vectors[1:]

        scores = target_vectors @ source_vector
        if not self.normalize:
            denominator = np.linalg.norm(target_vectors, axis=1) * np.linalg.norm(source_vector)
            scores = scores / np.clip(denominator, 1e-12, None)

        order = np.argsort(-scores)
        return [(int(i), targets[int(i)], float(scores[int(i)])) for i in order]


@lru_cache
def get_embedding_service() -> EmbeddingService:
    settings = get_settings()
    return EmbeddingService(
        model_name=settings.embedding_model,
        device=settings.embedding_device,
        normalize=settings.embedding_normalize,
    )
