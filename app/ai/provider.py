"""Base class for AI providers."""

from abc import ABC, abstractmethod


class AIProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str, context: str = "") -> str:
        ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...

    def test_connection(self) -> bool:
        result = self.complete("Say 'ok'.", "")
        return bool(result)
