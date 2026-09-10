"""Model-backed summaries for offline trajectory compression."""

import asyncio
import time
from typing import Optional

from agent.retry_utils import jittered_backoff
from superforecasting_agent.trajectories.compression_types import TrajectoryMetrics


def _effective_temperature_for_model(
    model: str,
    requested_temperature: float,
    base_url: Optional[str] = None,
) -> Optional[float]:
    """Apply fixed model temperature contracts to direct client calls.

    Returns ``None`` when the model manages temperature server-side (Kimi);
    callers must omit the ``temperature`` kwarg entirely in that case.
    """
    try:
        from agent.auxiliary_client import _fixed_temperature_for_model, OMIT_TEMPERATURE
    except Exception:
        return requested_temperature

    fixed_temperature = _fixed_temperature_for_model(model, base_url)
    if fixed_temperature is OMIT_TEMPERATURE:
        return None  # caller must omit temperature
    if fixed_temperature is not None:
        return fixed_temperature
    return requested_temperature


def _generate_summary(self, content: str, metrics: TrajectoryMetrics) -> str:
    """
        Generate a summary of the compressed turns using OpenRouter.
        
        Args:
            content: The content to summarize
            metrics: Metrics object to update
            
        Returns:
            Summary string
        """
    prompt = f"""Summarize the following agent conversation turns concisely. This summary will replace these turns in the conversation history.

Write the summary from a neutral perspective describing what the assistant did and learned. Include:
1. What actions the assistant took (tool calls, searches, file operations)
2. Key information or results obtained
3. Any important decisions or findings
4. Relevant data, file names, values, or outputs

Keep the summary factual and informative. Target approximately {self.config.summary_target_tokens} tokens.

---
TURNS TO SUMMARIZE:
{content}
---

Write only the summary, starting with "[CONTEXT SUMMARY]:" prefix."""

    for attempt in range(self.config.max_retries):
        try:
            metrics.summarization_api_calls += 1
            summary_temperature = _effective_temperature_for_model(
                self.config.summarization_model,
                self.config.temperature,
                self.config.base_url,
            )

            if getattr(self, '_use_call_llm', False):
                from agent.auxiliary_client import call_llm
                response = call_llm(
                    provider=self._llm_provider,
                    model=self.config.summarization_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=summary_temperature,
                    max_tokens=self.config.summary_target_tokens * 2,
                )
            else:
                _create_kwargs = {
                    "model": self.config.summarization_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": self.config.summary_target_tokens * 2,
                }
                if summary_temperature is not None:
                    _create_kwargs["temperature"] = summary_temperature
                response = self.client.chat.completions.create(**_create_kwargs)

            summary = self._coerce_summary_content(response.choices[0].message.content)
            return self._ensure_summary_prefix(summary)

        except Exception as e:
            metrics.summarization_errors += 1
            self.logger.warning(f"Summarization attempt {attempt + 1} failed: {e}")

            if attempt < self.config.max_retries - 1:
                time.sleep(jittered_backoff(attempt + 1, base_delay=self.config.retry_delay, max_delay=30.0))
            else:
                # Fallback: create a basic summary
                return "[CONTEXT SUMMARY]: [Summary generation failed - previous turns contained tool calls and responses that have been compressed to save context space.]"


async def _generate_summary_async(self, content: str, metrics: TrajectoryMetrics) -> str:
    """
        Generate a summary of the compressed turns using OpenRouter (async version).
        
        Args:
            content: The content to summarize
            metrics: Metrics object to update
            
        Returns:
            Summary string
        """
    prompt = f"""Summarize the following agent conversation turns concisely. This summary will replace these turns in the conversation history.

Write the summary from a neutral perspective describing what the assistant did and learned. Include:
1. What actions the assistant took (tool calls, searches, file operations)
2. Key information or results obtained
3. Any important decisions or findings
4. Relevant data, file names, values, or outputs

Keep the summary factual and informative. Target approximately {self.config.summary_target_tokens} tokens.

---
TURNS TO SUMMARIZE:
{content}
---

Write only the summary, starting with "[CONTEXT SUMMARY]:" prefix."""

    for attempt in range(self.config.max_retries):
        try:
            metrics.summarization_api_calls += 1
            summary_temperature = _effective_temperature_for_model(
                self.config.summarization_model,
                self.config.temperature,
                self.config.base_url,
            )

            if getattr(self, '_use_call_llm', False):
                from agent.auxiliary_client import async_call_llm
                response = await async_call_llm(
                    provider=self._llm_provider,
                    model=self.config.summarization_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=summary_temperature,
                    max_tokens=self.config.summary_target_tokens * 2,
                )
            else:
                _create_kwargs = {
                    "model": self.config.summarization_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": self.config.summary_target_tokens * 2,
                }
                if summary_temperature is not None:
                    _create_kwargs["temperature"] = summary_temperature
                response = await self._get_async_client().chat.completions.create(**_create_kwargs)

            summary = self._coerce_summary_content(response.choices[0].message.content)
            return self._ensure_summary_prefix(summary)

        except Exception as e:
            metrics.summarization_errors += 1
            self.logger.warning(f"Summarization attempt {attempt + 1} failed: {e}")

            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(jittered_backoff(attempt + 1, base_delay=self.config.retry_delay, max_delay=30.0))
            else:
                # Fallback: create a basic summary
                return "[CONTEXT SUMMARY]: [Summary generation failed - previous turns contained tool calls and responses that have been compressed to save context space.]"
