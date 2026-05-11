from __future__ import annotations

import asyncio
import json
from typing import Dict, Any, Optional, List, AsyncIterator, Tuple

from crewai import Agent, Task, Crew
from crewai.types.streaming import StreamChunkType
from crewai_tools import TavilySearchTool
from langfuse import observe, get_client
from litellm.caching.redis_semantic_cache import RedisSemanticCache
from nemoguardrails import LLMRails

from src.settings import SETTINGS
from src.utils import (
    format_chat_history,
    format_retrieved_context,
    normalize_semantic_cache_hit,
    parse_groundedness_result,
    parse_rag_decision_result,
)
from src.utils.decorators import agent_response_time
from src.services import prompts
from src.services.redis_cache import redis_cache
from src.services.retrieval import RetrievalService
from src.services.memory import ShortTermMemoryService
from src.services.memory import LongTermMemoryService
from src.services.litellm_client import get_qwen_llm, get_gpt_api_llm
from src.services.tools.retrieval_tool import RetrievalTool
from src.services.tools.long_term_memory_tool import LongTermMemoryTool
from src.services.tools.short_term_memory_tool import ShortTermMemoryTool



class LearningAgents:
    """Agents for the learning-assistant pipeline:

    User question → create_rag_decision_agent (decide: use RAG or answer directly)
        → If use_rag=False: create_direct_answer_agent (short direct answer, no groundedness check)
        → If use_rag=True: create_retrieval_agent → create_check_groundedness_agent
            → If SUPPORTED: return retrieval answer
            → If UNSUPPORTED: create_search_agent → return answer
    """
    def __init__(self):
        self.retrieval_tool = RetrievalTool()
        self.long_term_memory_tool = LongTermMemoryTool()
        self.short_term_memory_tool = ShortTermMemoryTool()
        # Qwen is used for routing / direct answers, OpenAI (gpt-api) for RAG & checks.
        self.qwen_llm = get_qwen_llm()
        self.gpt_llm = get_gpt_api_llm()

    def create_rag_decision_agent(self) -> Agent:
        """Create an agent that decides whether the question needs RAG (course/lecture) or not.

        This agent only returns JSON with a use_rag flag; it does not generate the final answer.
        """
        return Agent(
            role=prompts.RAG_DECISION_ROLE,
            goal=prompts.RAG_DECISION_GOAL,
            backstory=prompts.RAG_DECISION_BACKSTORY,
            tools=[],
            verbose=True,
            max_iterations=1,
            # llm=self.qwen_llm,
            llm=self.gpt_llm,
        )

    def create_direct_answer_agent(self) -> Agent:
        """Create an agent that gives short, direct answers when RAG is not needed."""
        return Agent(
            role=prompts.DIRECT_ANSWER_ROLE,
            goal=prompts.DIRECT_ANSWER_GOAL,
            backstory=prompts.DIRECT_ANSWER_BACKSTORY,
            tools=[],
            verbose=True,
            max_iterations=1,
            # llm=self.qwen_llm,
            llm=self.gpt_llm,
        )

    def create_retrieval_agent(self) -> Agent:
        """Create an agent that retrieves information from the lecture materials (first step in pipeline)."""
        return Agent(
            role=prompts.RETRIEVAL_ROLE,
            goal=prompts.RETRIEVAL_GOAL,
            backstory=prompts.RETRIEVAL_BACKSTORY,
            tools=[self.retrieval_tool, self.short_term_memory_tool],
            verbose=True,
            max_iterations=2,
            llm=self.gpt_llm,
        )

    def create_check_groundedness_agent(self) -> Agent:
        """Create an agent that checks if the retrieval answer is fully supported by the context (second step in pipeline)."""
        return Agent(
            role=prompts.GROUNDEDNESS_ROLE,
            goal=prompts.GROUNDEDNESS_GOAL,
            backstory=prompts.GROUNDEDNESS_BACKSTORY,
            verbose=True,
            max_iterations=2,
            llm=self.gpt_llm,
        )

    def create_search_agent(self) -> Agent:
        """Create an agent that searches the web when the retrieval answer was UNSUPPORTED (fallback in pipeline)."""
        return Agent(
            role=prompts.SEARCH_ROLE,
            goal=prompts.SEARCH_GOAL,
            backstory=prompts.SEARCH_BACKSTORY,
            tools=[TavilySearchTool(), self.short_term_memory_tool],
            verbose=True,
            max_iterations=2,
            llm=self.gpt_llm,
        )


class LearningOrchestrator:
    """Runs the pipeline:

    RAG decision → if use_rag then retrieval → groundedness check → return answer or search fallback;
    else direct answer (no RAG) with use_rag=False.
    """

    def __init__(self):
        self.agents = LearningAgents()
        self.rag_decision_agent = self.agents.create_rag_decision_agent()
        self.direct_answer_agent = self.agents.create_direct_answer_agent()
        self.retrieval_agent = self.agents.create_retrieval_agent()
        self.check_groundedness_agent = self.agents.create_check_groundedness_agent()
        self.search_agent = self.agents.create_search_agent()
        self._retrieval_service = RetrievalService()
        self._short_term_memory = ShortTermMemoryService()
        self._long_term_memory = LongTermMemoryService()
        self.langfuse = get_client()
        # Semantic cache for question → answer, using same Redis instance as app
        redis_password = (
            SETTINGS.REDIS_PASSWORD.get_secret_value()
            if SETTINGS.REDIS_PASSWORD is not None
            else ""
        )
        redis_url = f"redis://:{redis_password}@{SETTINGS.REDIS_HOST}:{SETTINGS.REDIS_PORT}"
        # Slightly relaxed threshold so similar phrasings still hit.
        self.semantic_cache = RedisSemanticCache(
            similarity_threshold=0.6,
            redis_url=redis_url,
            embedding_model="text-embedding-3-small",
        )

    async def _generate_session_title(self, first_message: str) -> str:
        """Generate a very short, concise title for a chat session using LiteLLM."""
        import litellm

        try:
            prompt = (
                "Generate a very short, concise title (max 5-6 words) for a chat session "
                f"based on this first message: '{first_message}'. Return only the title text, "
                "no quotes or extra explanation."
            )
            # Use the already-configured LLM settings from your agents service
            response = await litellm.acompletion(
                model="openai/gpt-api",  # Add openai/ prefix so LiteLLM knows the protocol
                messages=[{"role": "user", "content": prompt}],
                base_url=self.agents.gpt_llm.base_url or SETTINGS.OPENAI_BASE_URL,
                api_key=self.agents.gpt_llm.api_key or SETTINGS.OPENAI_API_KEY.get_secret_value(),
                temperature=0.7,
                max_tokens=20,
            )
            title = response.choices[0].message.content.strip()
            # Clean up quotes if any
            title = title.strip('"').strip("'")
            return title
        except Exception as e:
            print(f"Error generating session title for message '{first_message[:50]}...': {e}")
            import traceback
            traceback.print_exc()
            return "New Chat"

    async def _get_cached_answer(
        self,
        question: str,
        user_id: str,
        session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Try to fetch a semantically similar cached answer for this question."""
        if not self.semantic_cache:
            print("Semantic cache is not initialized; skipping cache lookup.")
            return None

        messages: List[Dict[str, Any]] = [{"role": "user", "content": question}]
        try:
            cached = await self.semantic_cache.async_get_cache(
                key="learning-session",
                messages=messages,
                metadata={"user_id": user_id, "session_id": session_id},
            )
        except Exception as e:
            print(f"Semantic cache lookup failed with error: {e}")
            return None

        if cached is None:
            print(f"Semantic cache MISS for question: {question}")
            return None

        print(f"Semantic cache RAW HIT for question: {question}, type={type(cached).__name__}")

        normalized = normalize_semantic_cache_hit(cached)
        if normalized is not None:
            return normalized

        print(
            "Semantic cache HIT but payload had no usable assistant text; treating as MISS."
        )
        return None

    @redis_cache.cache(ttl=10)
    async def _compute_answer(
        self,
        question: str,
        session_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """Run the pipeline (guardrails or orchestrator) and return the answer. Cached by redis_cache (exact key)."""
        rails_service: Optional[LLMRails] = getattr(
            self, "_current_rails_service", None
        )
        if rails_service:
            messages: List[Dict[str, Any]] = [
                {
                    "role": "context",
                    "content": {"user_id": user_id, "session_id": session_id},
                },
                {"role": "user", "content": question},
            ]
            guardrails_result = await rails_service.generate_async(messages=messages)
            
            if isinstance(guardrails_result, dict):
                response = guardrails_result.get("content", "") or ""
            elif isinstance(guardrails_result, str):
                response = guardrails_result
            else:
                response = str(guardrails_result) if guardrails_result else ""
            print(f"Guardrails result: {response}")
            await self._append_to_chat_history(session_id, user_id, question, response)
            return {"response": response, "use_rag": None}
        print("No guardrails service provided, proceeding with LLM generation.")
        result = await self.answer_question(question, session_id, user_id)
        print(f"Response: {result.get('response', '')}")
        return result

    async def _get_chat_history_str(
        self, session_id: Optional[str], user_id: Optional[str]
    ) -> str:
        """Load chat history from short-term memory and format for prompts."""
        if not session_id or not user_id:
            return "No previous conversation."
        ctx = await self._short_term_memory.get_conversation_context(
            session_id, user_id
        )
        if not ctx:
            return "No previous conversation."
        messages = (ctx.get("context") or {}).get("messages") or []
        return format_chat_history(messages)

    async def _append_to_chat_history(
        self,
        session_id: Optional[str],
        user_id: Optional[str],
        user_message: str,
        assistant_message: str,
        ttl_minutes: int = 60,
        max_messages: int = 5,
    ) -> None:
        """Append a user/assistant turn to short-term memory (Redis)."""
        if not session_id or not user_id:
            return
        try:
            print(f"Appending to chat history for session {session_id} and user {user_id}")
            existing = await self._short_term_memory.get_conversation_context(
                session_id, user_id
            )
            messages = (existing or {}).get("context", {}).get("messages") or []
            if not isinstance(messages, list):
                messages = []

            u = (user_message or "").strip()
            a = (assistant_message or "").strip()
            if u:
                messages.append({"role": "user", "content": u})
            if a:
                messages.append({"role": "assistant", "content": a})

            if max_messages and len(messages) > max_messages:
                messages = messages[-max_messages:]

            await self._short_term_memory.store_conversation_context(
                session_id=session_id,
                user_id=user_id,
                context={"messages": messages},
                ttl_minutes=ttl_minutes,
            )

            # Also store each message in long-term memory (Postgres)
            if u:
                await self._long_term_memory.store_chat_message(
                    user_id=user_id, session_id=session_id, role="user", content=u
                )
            if a:
                await self._long_term_memory.store_chat_message(
                    user_id=user_id, session_id=session_id, role="assistant", content=a
                )

            # Handle session title generation if it doesn't exist
            if session_id and user_id:
                existing_session = await self._long_term_memory.get_chat_session(
                    session_id, user_id
                )
                if not existing_session and u:
                    title = await self._generate_session_title(u)
                    await self._long_term_memory.create_chat_session(
                        session_id, user_id, title
                    )
                    print(f"Created session title for {session_id}: {title}")

            print(f"Chat history updated for session {session_id} and user {user_id}")
        except Exception as e:
            print(f"Error updating conversation context: {e}")

    @observe(name="learning-orchestrator")
    async def answer_question(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        langfuse_client = get_client()
        chat_history_str = await self._get_chat_history_str(session_id, user_id)

        print(f"Chat history: {chat_history_str}")

        # 0. RAG decision: is this question about technical/course content (use RAG) or not?
        rag_decision_task = Task(
            description=prompts.RAG_DECISION_TASK_DESCRIPTION,
            expected_output=prompts.RAG_DECISION_EXPECTED_OUTPUT,
            agent=self.rag_decision_agent,
        )
        rag_decision_crew = Crew(agents=[self.rag_decision_agent], tasks=[rag_decision_task])
        with langfuse_client.start_as_current_observation(
            name="rag_decision_agent",
            as_type="agent",
            input={"question": question, "chat_history": chat_history_str},
        ) as obs:
            rag_result = await rag_decision_crew.kickoff_async(
                inputs={"question": question, "chat_history": chat_history_str}
            )
            decision = parse_rag_decision_result(rag_result.raw)
            obs.update(output=decision)

        if not decision.get("use_rag", True):
            # No RAG: get a short, direct answer from the direct-answer agent; no groundedness check.
            direct_answer_task = Task(
                description=prompts.DIRECT_ANSWER_TASK_DESCRIPTION,
                expected_output=prompts.DIRECT_ANSWER_EXPECTED_OUTPUT,
                agent=self.direct_answer_agent,
            )
            direct_answer_crew = Crew(
                agents=[self.direct_answer_agent], tasks=[direct_answer_task]
            )
            with langfuse_client.start_as_current_observation(
                name="direct_answer_agent",
                as_type="agent",
                input={"question": question, "chat_history": chat_history_str},
            ) as obs:
                direct_result = await direct_answer_crew.kickoff_async(
                    inputs={"question": question, "chat_history": chat_history_str}
                )
                response = direct_result.raw
                obs.update(output={"direct_response": response})

            print(f"RAG decision: use_rag=False, direct response: {response[:80]}...")
            await self._append_to_chat_history(session_id, user_id, question, response)
            return {"response": response, "use_rag": False}

        # 1. Retrieval: answer from lecture materials
        retrieval_task = Task(
            description=prompts.RETRIEVAL_TASK_DESCRIPTION,
            expected_output=prompts.RETRIEVAL_EXPECTED_OUTPUT,
            agent=self.retrieval_agent,
        )
        retrieval_crew = Crew(agents=[self.retrieval_agent], tasks=[retrieval_task])
        with langfuse_client.start_as_current_observation(
            name="retrieval_agent",
            as_type="agent",
            input={"question": question, "chat_history": chat_history_str},
        ) as obs:
            retrieval_result = await retrieval_crew.kickoff_async(
                inputs={"question": question, "chat_history": chat_history_str}
            )
            retrieval_answer = retrieval_result.raw
            obs.update(output={"retrieval_answer": retrieval_answer})

        print(f"Retrieval answer: {retrieval_answer}")

        # 2. Get same context used by retrieval (for groundedness check)
        chunks_for_check = getattr(self.agents.retrieval_tool, "last_chunks", None)
        if isinstance(chunks_for_check, list) and chunks_for_check:
            context_str = format_retrieved_context(chunks_for_check)
        else:
            try:
                chunks_for_check = self._retrieval_service.retrieve_vector(question)
                context_str = format_retrieved_context(chunks_for_check)
            except Exception:
                context_str = "(Retrieval context unavailable)"

        # 3. Check groundedness: is the answer fully supported by the context?
        groundedness_task = Task(
            description=prompts.GROUNDEDNESS_TASK_DESCRIPTION,
            expected_output=prompts.GROUNDEDNESS_EXPECTED_OUTPUT,
            agent=self.check_groundedness_agent,
        )
        groundedness_crew = Crew(
            agents=[self.check_groundedness_agent],
            tasks=[groundedness_task],
        )
        with langfuse_client.start_as_current_observation(
            name="groundedness_check",
            as_type="guardrail",
            input={
                "question": question,
                "retrieval_answer": retrieval_answer,
                # Keep context reasonably sized in Langfuse
                "context_preview": context_str[:4000],
            },
        ) as obs:
            check_result = await groundedness_crew.kickoff_async(
                inputs={
                    "question": question,
                    "retrieval_answer": retrieval_answer,
                    "context": context_str,
                }
            )
            check_raw = check_result.raw
            verdict = parse_groundedness_result(check_raw)
            is_supported = (
                verdict.get("status", "UNSUPPORTED").strip().upper() == "SUPPORTED"
            )
            obs.update(
                output={
                    "verdict": verdict,
                    "is_supported": is_supported,
                }
            )

        print(f"Groundedness check result: {verdict}")

        # 4. Return retrieval only when SUPPORTED; otherwise run search (UNSUPPORTED covers "I don't know" and hallucination)
        if is_supported:
            await self._append_to_chat_history(
                session_id, user_id, question, retrieval_answer
            )
            return {"response": retrieval_answer, "use_rag": True}

        search_task = Task(
            description=prompts.SEARCH_TASK_DESCRIPTION,
            expected_output=prompts.SEARCH_EXPECTED_OUTPUT,
            agent=self.search_agent,
        )
        search_crew = Crew(agents=[self.search_agent], tasks=[search_task])
        with langfuse_client.start_as_current_observation(
            name="search_agent",
            as_type="agent",
            input={"question": question, "reason": verdict, "chat_history": chat_history_str},
        ) as obs:
            search_result = await search_crew.kickoff_async(inputs={"question": question, "chat_history": chat_history_str})
            response = search_result.raw
            obs.update(output={"search_answer": response})

        print("Using search tool to answer the question.")
        print(f"Search answer: {response}")
        await self._append_to_chat_history(session_id, user_id, question, response)
        return {"response": response, "use_rag": True}


    @agent_response_time
    async def generate(
        self,
        question: str,
        user_id: str,
        session_id: str,
        rails_service: Optional[LLMRails] = None,
    ) -> Dict[str, Any]:
        """Get answer from the agent pipeline. Response cached by redis_cache (ttl=10) via _compute_answer.
        Chat history is loaded from short-term memory (session_id/user_id); chat_history arg is accepted for API compatibility but not used."""
        langfuse_client = self.langfuse
        with langfuse_client.start_as_current_observation(
            name="learning-session",
            as_type="trace",
            input={"question": question, "user_id": user_id, "session_id": session_id},
        ) as obs:
            cached = await self._get_cached_answer(
                question=question, user_id=user_id, session_id=session_id
            )
            if cached is not None:
                obs.update(output={**cached, "from_cache": True})
                return cached

            if session_id or user_id:
                langfuse_client.update_current_trace(
                    session_id=session_id, user_id=user_id
                )

            self._current_rails_service = rails_service
            result = await self._compute_answer(question, session_id, user_id)

            # Save to semantic cache
            if self.semantic_cache:
                messages = [{"role": "user", "content": question}]
                metadata = {"user_id": user_id, "session_id": session_id}
                value_to_store = json.dumps(result)
                try:
                    await self.semantic_cache.async_set_cache(
                        key="learning-session",
                        value=value_to_store,
                        messages=messages,
                        metadata=metadata,
                        ttl=100,
                    )
                    print("Saved answer to semantic cache (ttl=10).")
                except Exception as e:
                    print(f"ERROR during semantic cache SET: {e}")
                    raise

            obs.update(output=result)
            return result

    
    async def generate_stream(
        self,
        *,
        question: str,
        user_id: str,
        session_id: str,
        rails_service: Optional[LLMRails] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Streaming version of `generate()`.

        Yields events token-by-token during generation using
        ``Crew(stream=True)`` + ``await crew.kickoff_async()``:

        Events are JSON objects (sent over SSE in the API layer):

        - ``{"type": "token", "content": "...", "source": "direct"|"retrieval"|"search"}``
          A text fragment to append to the current buffer.

        - ``{"type": "confirmed", "source": "retrieval"}``
          The optimistically streamed retrieval answer passed groundedness.

        - ``{"type": "rollback", "reason": "...", "verdict": {...}}``
          The retrieval answer failed groundedness; UI should clear buffer and expect a new stream.

        - ``{"type": "final", "response": "...", "use_rag": bool|None, "from_cache": bool, "final_source": str}``
        """
        langfuse_client = self.langfuse
        with langfuse_client.start_as_current_observation(
            name="learning-session-stream",
            as_type="trace",
            input={"question": question, "user_id": user_id, "session_id": session_id},
        ) as obs:
            # ── Semantic cache hit → emit final immediately, no streaming needed ──
            cached = await self._get_cached_answer(
                question=question, user_id=user_id, session_id=session_id
            )
            if cached is not None:
                obs.update(output={**cached, "from_cache": True})
                yield {
                    "type": "final",
                    "response": cached.get("response", ""),
                    "use_rag": cached.get("use_rag", None),
                    "from_cache": True,
                    "final_source": "cache",
                }
                return

            if session_id or user_id:
                langfuse_client.update_current_trace(session_id=session_id, user_id=user_id)

            # ── Guardrails path (non-streaming; rails produces a complete response) ──
            self._current_rails_service = rails_service
            if rails_service:
                messages: List[Dict[str, Any]] = [
                    {"role": "context", "content": {"user_id": user_id, "session_id": session_id}},
                    {"role": "user", "content": question},
                ]
                guardrails_result = await rails_service.generate_async(messages=messages)
                if isinstance(guardrails_result, dict):
                    response = guardrails_result.get("content", "") or ""
                elif isinstance(guardrails_result, str):
                    response = guardrails_result
                else:
                    response = str(guardrails_result) if guardrails_result else ""
                await self._append_to_chat_history(session_id, user_id, question, response)
                result = {"response": response, "use_rag": None}
                obs.update(output=result)
                yield {"type": "final", "response": response, "use_rag": None, "from_cache": False}
                return

            # ── Normal pipeline ──────────────────────────────────────────────────
            chat_history_str = await self._get_chat_history_str(session_id, user_id)

            # 0) RAG decision — routing only, no streaming needed
            rag_decision_task = Task(
                description=prompts.RAG_DECISION_TASK_DESCRIPTION,
                expected_output=prompts.RAG_DECISION_EXPECTED_OUTPUT,
                agent=self.rag_decision_agent,
            )
            rag_decision_crew = Crew(agents=[self.rag_decision_agent], tasks=[rag_decision_task])
            rag_result = await rag_decision_crew.kickoff_async(
                inputs={"question": question, "chat_history": chat_history_str}
            )
            decision = parse_rag_decision_result(getattr(rag_result, "raw", "") or "")

            final_response: str = ""
            use_rag: Optional[bool] = None

            if not decision.get("use_rag", True):
                # ── Branch A: direct answer, no RAG ─────────────────────────────
                direct_answer_task = Task(
                    description=prompts.DIRECT_ANSWER_STREAM_TASK_DESCRIPTION,
                    expected_output=prompts.DIRECT_ANSWER_EXPECTED_OUTPUT,
                    agent=self.direct_answer_agent,
                )
                direct_answer_crew = Crew(
                    agents=[self.direct_answer_agent],
                    tasks=[direct_answer_task],
                    stream=True,
                )
                # kickoff_async with stream=True returns a CrewStreamingOutput;
                # async-iterate it to receive TEXT tokens as they are generated.
                streaming = await direct_answer_crew.kickoff_async(
                    inputs={"question": question, "chat_history": chat_history_str}
                )
                async for chunk in streaming:
                    if chunk.chunk_type == StreamChunkType.TEXT and chunk.content:
                        yield {"type": "token", "content": chunk.content, "source": "direct"}
                # Must exhaust the iterator before accessing .result
                final_response = streaming.result.raw or ""
                use_rag = False
                final_source = "direct"

            else:
                # ── Branch B-1: retrieval answer (stream) ────────────────────────
                retrieval_task = Task(
                    description=prompts.RETRIEVAL_TASK_DESCRIPTION,
                    expected_output=prompts.RETRIEVAL_EXPECTED_OUTPUT,
                    agent=self.retrieval_agent,
                )
                retrieval_crew = Crew(
                    agents=[self.retrieval_agent],
                    tasks=[retrieval_task],
                    stream=True,
                )
                streaming = await retrieval_crew.kickoff_async(
                    inputs={"question": question, "chat_history": chat_history_str}
                )
                # Optimistically stream retrieval tokens immediately for responsiveness,
                # but keep a full-text buffer so we can run groundedness once complete.
                retrieval_stream_parts: List[str] = []
                async for chunk in streaming:
                    if chunk.chunk_type == StreamChunkType.TEXT and chunk.content:
                        retrieval_stream_parts.append(chunk.content)
                        yield {"type": "token", "content": chunk.content, "source": "retrieval"}

                retrieval_answer: str = streaming.result.raw or ""

                # ── Branch B-2: groundedness check (non-stream, routing only) ────
                chunks_for_check = getattr(self.agents.retrieval_tool, "last_chunks", None)
                if isinstance(chunks_for_check, list) and chunks_for_check:
                    context_str = format_retrieved_context(chunks_for_check)
                else:
                    # Fallback: only if tool state unavailable.
                    try:
                        chunks_for_check = self._retrieval_service.retrieve_vector(question)
                        context_str = format_retrieved_context(chunks_for_check)
                    except Exception:
                        chunks_for_check = []
                        context_str = "(Retrieval context unavailable)"

                groundedness_task = Task(
                    description=prompts.GROUNDEDNESS_STREAM_TASK_DESCRIPTION,
                    expected_output=prompts.GROUNDEDNESS_STREAM_EXPECTED_OUTPUT,
                    agent=self.check_groundedness_agent,
                )
                groundedness_crew = Crew(
                    agents=[self.check_groundedness_agent],
                    tasks=[groundedness_task],
                )
                # Run groundedness check concurrently with any UI rendering work.
                async def _run_groundedness() -> Tuple[Dict[str, str], bool]:
                    check_result = await groundedness_crew.kickoff_async(
                        inputs={
                            "question": question,
                            "retrieval_answer": retrieval_answer,
                            "context": context_str,
                        }
                    )
                    verdict = parse_groundedness_result(getattr(check_result, "raw", "") or "")
                    is_supported = (
                        verdict.get("status", "UNSUPPORTED").strip().upper() == "SUPPORTED"
                    )
                    return verdict, is_supported

                verdict, is_supported = await asyncio.create_task(_run_groundedness())

                if is_supported:
                    # Tell UI it can "lock in" the already-streamed retrieval answer.
                    yield {"type": "confirmed", "source": "retrieval"}
                    final_response = retrieval_answer
                    use_rag = True
                    final_source = "retrieval"
                else:
                    # Signal the UI to clear the optimistic buffer before we stream fallback.
                    yield {
                        "type": "rollback",
                        "reason": verdict.get("reason", "Groundedness check failed"),
                        "verdict": verdict,
                    }
                    # ── Branch B-3: web search fallback (stream) ─────────────────
                    search_task = Task(
                        description=prompts.SEARCH_STREAM_TASK_DESCRIPTION,
                        expected_output=prompts.SEARCH_STREAM_EXPECTED_OUTPUT,
                        agent=self.search_agent,
                    )
                    search_crew = Crew(
                        agents=[self.search_agent],
                        tasks=[search_task],
                        stream=True,
                    )
                    streaming = await search_crew.kickoff_async(
                        inputs={"question": question, "chat_history": chat_history_str}
                    )
                    async for chunk in streaming:
                        if chunk.chunk_type == StreamChunkType.TEXT and chunk.content:
                            yield {"type": "token", "content": chunk.content, "source": "search"}
                    final_response = streaming.result.raw or ""
                    use_rag = True
                    final_source = "search"

            # ── Persist history & cache, then emit final event ───────────────────
            final_response = final_response or ""
            await self._append_to_chat_history(session_id, user_id, question, final_response)

            result = {"response": final_response, "use_rag": use_rag}

            if self.semantic_cache:
                messages = [{"role": "user", "content": question}]
                metadata = {"user_id": user_id, "session_id": session_id}
                try:
                    await self.semantic_cache.async_set_cache(
                        key="learning-session",
                        value=json.dumps(result),
                        messages=messages,
                        metadata=metadata,
                        ttl=100,
                    )
                except Exception as e:
                    print(f"ERROR during semantic cache SET (stream): {e}")

            obs.update(output=result)
            yield {
                "type": "final",
                "response": final_response,
                "use_rag": use_rag,
                "from_cache": False,
                "final_source": final_source if "final_source" in locals() else None,
            }

