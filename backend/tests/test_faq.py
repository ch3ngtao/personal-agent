"""简历 FAQ（RAG）接口测试。

检索 / 切分相关的用例需要向量模型；模型或 PDF 不可用时自动 skip，保证离线也能跑通。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import clock
from app.main import app
from app.services import rag, retrieval


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def index_status(client: TestClient) -> dict:
    """构建索引；构建不了（缺 PDF / 缺模型）就跳过依赖它的用例。"""
    try:
        response = client.post("/api/faq/index")
    except Exception as exc:  # noqa: BLE001 - 例如向量模型无法下载
        pytest.skip(f"向量模型不可用，跳过检索相关用例：{exc}")

    if response.status_code != 200:
        pytest.skip(f"无法建立简历索引，跳过检索相关用例：{response.text}")
    return response.json()


def test_status_reports_resume_pdf(client: TestClient) -> None:
    body = client.get("/api/faq/status").json()

    assert body["pdf_name"] == rag.DEFAULT_PDF_NAME
    assert body["chunk_size"] > body["chunk_overlap"] > 0
    assert body["vector_store"] == "InMemoryVectorStore"
    # PDF 找得到就算可用，索引是首次检索时才真正构建
    assert body["ready"] is True


def test_pdf_path_comes_from_config(tmp_path: Path) -> None:
    """用哪份简历由配置决定，代码里只有兜底默认值。

    RESUME_PDF_PATH 比 RESUME_FILE 优先；两个都不配才退回仓库里那份默认简历。
    """
    custom = tmp_path / "另一份简历.pdf"
    custom.write_bytes(b"%PDF-1.4")

    assert rag.ResumeIndex.resolve_pdf_path(None, str(custom)) == custom.resolve()
    assert rag.ResumeIndex.resolve_pdf_path(str(custom), "简历-李四.pdf") == custom.resolve()

    fallback = rag.ResumeIndex.resolve_pdf_path(None, None)
    assert fallback is not None
    assert fallback.name == rag.DEFAULT_PDF_NAME


def test_chunks_are_split(client: TestClient, index_status: dict) -> None:
    body = client.get("/api/faq/chunks").json()

    assert body["total"] == index_status["chunks"] > 1
    assert len(body["chunks"]) == body["total"]
    assert all(chunk["chars"] > 0 for chunk in body["chunks"])
    assert all(chunk["page"] >= 1 for chunk in body["chunks"])
    # 每个 chunk 都不超过切分上限（留一点换行造成的边界误差）
    assert all(chunk["chars"] <= index_status["chunk_size"] + 40 for chunk in body["chunks"])


def test_chunks_carry_section_context(client: TestClient, index_status: dict) -> None:
    """结构感知切分：片段带章节，多条目章节额外有一条索引片段。"""
    chunks = client.get("/api/faq/chunks").json()["chunks"]
    sections = {chunk["section"] for chunk in chunks}

    assert {"求职意向", "相关技能", "工作经历", "项目经历"} <= sections
    # 正文片段带上章节前缀，避免公司名和经历详情被切散
    work_chunks = [chunk for chunk in chunks if chunk["section"] == "工作经历"]
    assert any(chunk["content"].startswith("【工作经历】") for chunk in work_chunks)

    # 索引片段只列条目名，供「他最近在哪家公司」这类问题命中
    index_chunk = next(chunk for chunk in chunks if "·索引" in chunk["content"])
    assert index_chunk["section"] == "工作经历"
    assert "星垠智能科技" in index_chunk["content"]
    assert index_chunk["chars"] < index_status["chunk_size"]


def test_search_finds_current_employer(client: TestClient, index_status: dict) -> None:
    response = client.post("/api/faq/search", json={"query": "他现在的公司是哪家？", "top_k": 5})
    assert response.status_code == 200

    matches = response.json()["matches"]

    assert any("星垠智能科技" in match["content"] for match in matches)


def test_search_covers_whole_section(client: TestClient, index_status: dict) -> None:
    """问「有哪些项目经验」时要把该节条目给全，只取 top-k 会漏掉一半项目。"""
    response = client.post("/api/faq/search", json={"query": "有哪些项目经验？", "top_k": 5})
    assert response.status_code == 200

    matches = response.json()["matches"]
    joined = "\n".join(match["content"] for match in matches)

    # 【项目经历】正文里的 4 个项目
    for name in ("智核 AI 平台", "云湃 SASS", "擎宇 SASS 平台", "XXXOA 平台"):
        assert name in joined
    # 末尾补充的【其他项目】也要带上，否则会漏掉一串项目
    for name in ("智核 AI 开放平台", "云湃容器调度平台", "擎宇工单中台", "运营实时数据大屏"):
        assert name in joined
    # 整节返回，但不会把整份简历都塞进上下文
    assert 0 < len(matches) < index_status["chunks"]


def test_related_sections_are_grouped() -> None:
    """项目 / 工作这类会分节写的内容，问一节要带上它的补充章节。"""
    assert rag.match_sections("有哪些项目经验？") == ["项目经历", "其他项目"]
    assert rag.match_sections("介绍下工作经历") == ["工作经历", "实习经历"]
    # 明确问补充章节时不需要反过来带上主体章节
    assert rag.match_sections("其他项目有哪些") == ["其他项目"]
    assert rag.match_sections("帮我写段代码") == []


def test_merge_group_dedupes_overlap() -> None:
    """同一条目的碎片合并时，重复的段落标题与 overlap 都要去掉。"""
    header = "2023.07-至今 A 项目"
    group = [
        rag.ResumeChunk(
            index=0,
            content=f"【项目经历】\n{header}\n前端负责人\n1. 优化打包体积",
            section="项目经历",
        ),
        rag.ResumeChunk(
            index=1,
            content=f"【项目经历】\n{header}\n化打包体积由 2 MB 降到 1 MB。\n2. 第二点",
            section="项目经历",
        ),
    ]

    merged = rag._merge_group(group, overlap=8)

    assert merged.content.count(header) == 1
    assert merged.content.count("化打包体积") == 1
    assert "2. 第二点" in merged.content


def test_resume_prompt_injects_today() -> None:
    """简历链路也要告诉模型今天是几号，否则「2022.10-至今」判断不了是否在职。"""
    index = rag.get_resume_index()

    messages = index.build_messages("他现在还在星垠智能科技吗？", [])

    assert clock.describe(with_time=False) in messages[0]["content"]
    assert "至今" in messages[0]["content"]


def test_search_ranks_matching_chunk_first(client: TestClient, index_status: dict) -> None:
    response = client.post("/api/faq/search", json={"query": "期望薪资是多少？", "top_k": 5})
    assert response.status_code == 200

    matches = response.json()["matches"]
    scores = [match["score"] for match in matches]

    assert matches
    assert scores == sorted(scores, reverse=True)
    assert all(0 <= score <= 1 for score in scores)
    assert any("期望薪资" in match["content"] for match in matches)


class _UnconfiguredLLM:
    """模拟没配 DEEPSEEK_API_KEY 的情况。"""

    model = "deepseek-chat"
    configured = False


def test_ask_without_api_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.routes.faq.get_deepseek_service", _UnconfiguredLLM)

    response = client.post("/api/faq/ask", json={"question": "他的期望薪资是多少？"})

    assert response.status_code == 503
    assert "DEEPSEEK_API_KEY" in response.json()["detail"]


def test_ask_stream_without_api_key(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.routes.faq.get_deepseek_service", _UnconfiguredLLM)

    with client.stream("POST", "/api/faq/ask/stream", json={"question": "hi"}) as response:
        assert response.status_code == 200
        events = [line for line in response.iter_lines() if line.startswith("data: ")]

    payload = json.loads(events[0][len("data: ") :])
    assert "DEEPSEEK_API_KEY" in payload["error"]
    assert events[-1] == "data: [DONE]"


def test_tokenize_splits_chinese_into_bigrams() -> None:
    tokens = retrieval.tokenize("期望薪资 Vue3")

    assert "期望" in tokens
    assert "薪资" in tokens
    assert "vue3" in tokens


def test_bm25_favors_matching_chunk() -> None:
    bm25 = retrieval.BM25(["求职意向：期望薪资面议", "熟悉 Vue3 与 React 技术栈"])

    scores = bm25.scores("薪资多少")

    assert scores[0] > scores[1]
