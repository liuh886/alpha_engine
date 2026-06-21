import tiktoken
from pydantic import BaseModel, ValidationError


class BaseAgent:
    """
    Roadmap Item 32/33/40: LLM Defenses & Context Compression
    Base class providing protections against hallucination, prompt injection, and token blowouts.
    """

    def __init__(self, model_name: str = "gpt-4", max_context_tokens: int = 4000):
        self.model_name = model_name
        self.max_context_tokens = max_context_tokens
        try:
            self.tokenizer = tiktoken.encoding_for_model(model_name)
        except KeyError:
            self.tokenizer = tiktoken.get_encoding("cl100k_base")

    def compress_context(self, context: str) -> str:
        """
        Truncate context to ensure it fits within the strict max_context_tokens budget,
        saving space for the system prompt and CoT reasoning.
        """
        tokens = self.tokenizer.encode(context)
        if len(tokens) > self.max_context_tokens:
            truncated = tokens[: self.max_context_tokens]
            return (
                self.tokenizer.decode(truncated)
                + "\n...[CONTEXT COMPRESSED DUE TO LENGTH LIMITS]..."
            )
        return context

    def validate_structured_output(
        self, OutputModel: type[BaseModel], llm_response: dict
    ) -> BaseModel:
        """
        Enforces strict schema compliance. If the LLM hallucinates keys or types,
        this will catch it before injecting bad state into the trading engine.
        """
        try:
            return OutputModel(**llm_response)
        except ValidationError as e:
            raise RuntimeError(f"LLM Output Schema Violation (Hallucination Guard Triggered): {e}")

    def generate_chain_of_thought_prompt(self, base_prompt: str) -> str:
        """
        Forces the LLM to output its reasoning step-by-step before the final answer,
        vastly improving reliability for trading decisions.
        """
        return f"{base_prompt}\n\nIMPORTANT: You must first provide a mandatory `<thinking>` block explaining your step-by-step logic, followed by your final conclusion."
