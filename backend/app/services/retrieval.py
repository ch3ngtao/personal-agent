"""检索打分：向量相似度 + BM25 关键词，加权融合成一个 0~1 的相关度。

简历索引和「补充知识库」共用这一套打分，避免两处各写一份。
中文不引入分词依赖：英文/数字按词切，中文按字符二元组切。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence

# Okapi BM25 的经典取值与两路打分的融合权重。
BM25_K1 = 1.5
BM25_B = 0.75
VECTOR_WEIGHT = 0.6
KEYWORD_WEIGHT = 0.4

_TOKEN_RE = re.compile(r"[a-z0-9+#.]+|[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """轻量分词：英文/数字按词，中文按字符二元组。

    对「Vue3」「LangChain」这类技术词天然友好，也省掉一个 jieba 依赖。
    """
    tokens: list[str] = []
    for segment in _TOKEN_RE.findall(text.lower()):
        if segment[0].isascii() or len(segment) == 1:
            tokens.append(segment)
        else:
            tokens.extend(segment[i : i + 2] for i in range(len(segment) - 1))
    return tokens


class BM25:
    """极简 BM25，够用在简历 / 笔记这种小语料上。"""

    def __init__(self, corpus: Sequence[str]) -> None:
        self.doc_tokens = [Counter(tokenize(text)) for text in corpus]
        self.doc_lengths = [sum(tokens.values()) for tokens in self.doc_tokens]
        self.avg_length = (sum(self.doc_lengths) / len(self.doc_lengths)) if self.doc_tokens else 0.0

        document_frequency: Counter[str] = Counter()
        for tokens in self.doc_tokens:
            document_frequency.update(tokens.keys())
        self.document_frequency = document_frequency
        self.total = len(self.doc_tokens)

    def idf(self, token: str) -> float:
        frequency = self.document_frequency.get(token, 0)
        return math.log(1 + (self.total - frequency + 0.5) / (frequency + 0.5))

    def scores(self, query: str) -> list[float]:
        query_tokens = set(tokenize(query))
        if not query_tokens:
            return [0.0] * self.total

        results: list[float] = []
        for tokens, length in zip(self.doc_tokens, self.doc_lengths, strict=True):
            score = 0.0
            for token in query_tokens:
                frequency = tokens.get(token, 0)
                if not frequency:
                    continue
                denominator = frequency + BM25_K1 * (1 - BM25_B + BM25_B * length / (self.avg_length or 1.0))
                score += self.idf(token) * frequency * (BM25_K1 + 1) / denominator
            results.append(score)
        return results


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def rank(
    query: str,
    vector_scores: Mapping[int, float],
    *,
    top_k: int,
    bm25: BM25 | None = None,
    hybrid: bool = True,
    candidate_limit: int | None = None,
) -> list[tuple[int, float]]:
    """把向量打分（可能只有候选子集）融合成排序结果。

    返回 ``[(下标, 相关度 0~1), ...]``，按相关度降序。``hybrid=False`` 时只用向量。
    """
    if not vector_scores:
        return []

    if not hybrid or bm25 is None:
        ordered = sorted(vector_scores.items(), key=lambda item: -item[1])
        return [(index, _clamp(score)) for index, score in ordered[:top_k]]

    keyword_scores = bm25.scores(query)
    pool = candidate_limit or max(top_k * 4, 12)
    keyword_top = sorted(range(len(keyword_scores)), key=lambda i: (-keyword_scores[i], i))[:pool]
    candidate_ids = list(dict.fromkeys([*vector_scores, *keyword_top]))

    vector_values = [vector_scores[index] for index in candidate_ids if index in vector_scores]
    vector_min = min(vector_values, default=0.0)
    vector_max = max(vector_values, default=0.0)
    keyword_max = max((keyword_scores[index] for index in candidate_ids), default=0.0) or 1.0

    fused: list[tuple[int, float]] = []
    for index in candidate_ids:
        if vector_max > vector_min and index in vector_scores:
            normalized_vector = (vector_scores[index] - vector_min) / (vector_max - vector_min)
        else:
            normalized_vector = 0.0
        normalized_keyword = keyword_scores[index] / keyword_max
        fused.append((index, VECTOR_WEIGHT * normalized_vector + KEYWORD_WEIGHT * normalized_keyword))

    fused.sort(key=lambda item: (-item[1], item[0]))
    return [(index, _clamp(score)) for index, score in fused[:top_k]]
