"""Knowledge base for COMSOL MCP Server."""

from .embedded import register_knowledge_tools
from .pdf_processor import PDFProcessor, check_pdf_dependencies, DEFAULT_PDF_DIR
from .retriever import VectorRetriever, get_retriever, search_docs, DEFAULT_DB_DIR

__all__ = [
    "register_knowledge_tools",
    "PDFProcessor",
    "check_pdf_dependencies",
    "VectorRetriever",
    "get_retriever",
    "search_docs",
    "DEFAULT_PDF_DIR",
    "DEFAULT_DB_DIR",
]