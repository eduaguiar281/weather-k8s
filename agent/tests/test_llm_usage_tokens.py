"""Testes para extração de usage de tokens da resposta LangChain."""

from __future__ import annotations

import unittest

from alert_agent.infra.llm.usage import extract_llm_usage_tokens


class ExtractLlmUsageTokensTests(unittest.TestCase):
    def test_usage_metadata_langchain_style(self):
        class R:
            usage_metadata = {"input_tokens": 100, "output_tokens": 42}

        self.assertEqual(extract_llm_usage_tokens(R()), (100, 42))

    def test_prompt_completion_aliases(self):
        class R:
            usage_metadata = {"prompt_tokens": 7, "completion_tokens": 9}

        self.assertEqual(extract_llm_usage_tokens(R()), (7, 9))

    def test_response_metadata_usage_fallback(self):
        class R:
            usage_metadata = None
            response_metadata = {"usage": {"input_tokens": "3", "output_tokens": "4"}}

        self.assertEqual(extract_llm_usage_tokens(R()), (3, 4))

    def test_invalid_usage_values_yield_none(self):
        class R:
            usage_metadata = {"input_tokens": "nope", "output_tokens": "x"}

        self.assertEqual(extract_llm_usage_tokens(R()), (None, None))


if __name__ == "__main__":
    unittest.main()
