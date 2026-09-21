"""Self-contained fakes for text_agent's genuinely external dependencies.

Modeled on the shapes documented by RespondService's constructor
(text_agent/app/src/services/respond.py) and cross-checked against the
duck-typed interfaces exercised by infra/agent/knowledge.py, infra/agent/*,
and infra/knowledge/reader.py. Deliberately independent of tests/e2e/fakes.py
per the task's isolation rule -- these are owned by tests/api/text_agent only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class RespondCall:
    """One recorded call into the faked OpenAI Responses client."""

    model: str
    previous_response_id: Optional[str]
    input_message: list[Any]


class FakeOpenAIResponsesClient:
    """Scriptable, recording stand-in for infra.llm.oai.responses.OpenAIResponsesClient."""

    def __init__(self) -> None:
        self.calls: list[RespondCall] = []
        self.token_count_calls: list[Optional[str]] = []
        # Each entry is either a ChatTurn to return or an Exception to raise.
        self.script: list[Any] = []
        self.default: Optional[Any] = None
        self.next_tokens: int = 1000

    async def count_input_tokens(
        self,
        model: str,
        previous_response_id: Optional[str],
        input_message: Any,
    ) -> int:
        self.token_count_calls.append(previous_response_id)
        return self.next_tokens

    async def chat(self, **kwargs: Any) -> Any:
        """Return (or raise) the next scripted outcome, recording the call."""
        history = kwargs.get("history", kwargs.get("input_message", []))
        self.calls.append(
            RespondCall(
                model=kwargs.get("model", ""),
                previous_response_id=kwargs.get("previous_response_id"),
                input_message=list(history),
            )
        )
        outcome = self.script.pop(0) if self.script else self.default
        if outcome is None:
            raise AssertionError("FakeOpenAIResponsesClient.chat called with no script")
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return outcome(kwargs)
        return outcome


class FakeOpenAIImageClient:
    """Recording stand-in for infra.llm.oai.images.OpenAIImageClient."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.raise_on_generate: Optional[BaseException] = None

    async def generate(self, prompt: str) -> bytes:
        self.calls.append(("generate", prompt))
        if self.raise_on_generate is not None:
            raise self.raise_on_generate
        return b"fake-png-bytes"

    async def edit(self, prompt: str, source_images: list[Any]) -> bytes:
        self.calls.append(("edit", prompt))
        return b"fake-png-bytes"


class FakeEmbeddingClient:
    """Recording stand-in for infra.llm.gemini.embeddings.GeminiEmbeddingClient."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed_documents(self, parts: list[Any]) -> list[list[float]]:
        self.calls.append("embed_documents")
        return [[0.0, 0.0, 0.0] for _ in parts]

    async def embed_queries(self, parts: list[Any]) -> list[list[float]]:
        self.calls.append("embed_queries")
        return [[0.0, 0.0, 0.0] for _ in parts]


@dataclass
class GraphCall:
    """One recorded Cypher execution."""

    text: str
    params: dict[str, Any]


class FakeGraphClient:
    """Recording stand-in for infra.platform.graph.GraphClient with scriptable rows."""

    def __init__(self) -> None:
        self.calls: list[GraphCall] = []
        self.closed = False
        # Callable(text, params) -> list[dict]; default returns no rows.
        self.responder: Callable[[str, dict[str, Any]], list[dict[str, Any]]] = (
            lambda text, params: []
        )

    async def query(self, text: str, **params: Any) -> list[dict[str, Any]]:
        self.calls.append(GraphCall(text=text, params=dict(params)))
        return self.responder(text, params)

    async def close(self) -> None:
        self.closed = True


class FakeDocumentWorkerClient:
    """Recording stand-in for infra.clients.document_worker.DocumentWorkerClient.

    Never reached by the plain-text/success and negative-path tests in this
    suite: no scripted fake-LLM tool call requests document generation.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def close(self) -> None:
        return None


class FakeUsersClient:
    """Minimal fake standing in for infra.clients.users.client.UsersClient.

    RespondService's constructor is typed against the concrete UsersClient,
    but nothing in it calls a users method at construction time -- only tools
    invoked mid-turn (update_profile, enroll_ambassador, get_ambassador_status)
    would reach it. None of this suite's scripted turns trigger those tools,
    so this bare stand-in (never actually called) is sufficient; see
    UNCERTAINTY for why a live/faked user_service backend was not wired up.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def close(self) -> None:
        return None

    async def get_enrollment_ids(self, user_id: str):
        from infra.clients.users import EnrollmentIdsResponse

        return EnrollmentIdsResponse(teacherUserIds=[], studentUserIds=[])

    async def batch_get_users(self, user_ids: list[str]) -> list:
        return []


class FakeGcsBucket:
    """Minimal in-memory stand-in for infra.platform.storage.GcsBucket.

    Backs ConversationMediaStore for image/document generation tools built at
    turn-setup time; unused by any test in this suite since no scripted turn
    requests image or document generation.
    """

    def __init__(self, bucket_name: str = "fake-bucket") -> None:
        self._bucket = bucket_name
        self.objects: dict[str, bytes] = {}

    async def upload(self, object_name: str, data: bytes, content_type: str) -> None:
        self.objects[object_name] = data

    async def download(self, object_name: str) -> bytes:
        return self.objects[object_name]

    def public_url(self, object_name: str) -> str:
        return f"https://storage.googleapis.com/{self._bucket}/{object_name}"

    async def close(self) -> None:
        return None


@dataclass
class Fakes:
    """Every fake wired into one text_agent test app, for scripting per test."""

    openai: FakeOpenAIResponsesClient = field(default_factory=FakeOpenAIResponsesClient)
    openai_images: FakeOpenAIImageClient = field(default_factory=FakeOpenAIImageClient)
    embeddings: FakeEmbeddingClient = field(default_factory=FakeEmbeddingClient)
    graph: FakeGraphClient = field(default_factory=FakeGraphClient)
    documents: FakeDocumentWorkerClient = field(default_factory=FakeDocumentWorkerClient)
    users: FakeUsersClient = field(default_factory=FakeUsersClient)
    bucket: FakeGcsBucket = field(default_factory=FakeGcsBucket)
