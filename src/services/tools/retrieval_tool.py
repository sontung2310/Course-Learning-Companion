import json
from typing import Any, List, Dict, Optional

from crewai.tools import BaseTool

from src.services.retrieval import RetrievalService


retrieval_service = RetrievalService()


class RetrievalTool(BaseTool):
    """Tool for retrieving information using Retrieval service."""

    name: str = "retrieval"
    description: str = "Retrieve relevant documents and information using vector search through Retrieval service"
    # Best-effort: the orchestrator can reuse these chunks to avoid a second retrieval call.
    last_chunks: Optional[List[Dict[str, Any]]] = None

    def _run(self, question: str) -> str:
        """Run the tool with the given query."""
        try:
            chunks = retrieval_service.retrieve_vector(question)
            self.last_chunks = chunks
            # CrewAI tools return strings; JSON keeps metadata intact for citation.
            return json.dumps(chunks, ensure_ascii=False, default=str)
        except Exception as e:
            return f"Error retrieving information: {str(e)}"
