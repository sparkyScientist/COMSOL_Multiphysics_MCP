#!/usr/bin/env python
"""
Build the PDF documentation knowledge base for COMSOL MCP Server.

This script:
1. Scans the pdf/ directory for PDF files
2. Extracts and chunks text from each PDF
3. Creates embeddings and stores in ChromaDB

Usage:
    python scripts/build_knowledge_base.py [--limit N] [--rebuild]

Options:
    --limit N     Only process first N PDF files (for testing)
    --rebuild     Clear existing database and rebuild from scratch
    --no-mirror   Don't use HuggingFace mirror (for users outside China)
"""

import argparse
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def setup_mirror():
    """Setup HuggingFace mirror for users in China."""
    hf_mirror = "https://hf-mirror.com"
    if "HF_ENDPOINT" not in os.environ:
        os.environ["HF_ENDPOINT"] = hf_mirror
        print(f"[INFO] Using HuggingFace mirror: {hf_mirror}")


from src.knowledge.pdf_processor import PDFProcessor, DEFAULT_PDF_DIR, check_pdf_dependencies
from src.knowledge.retriever import VectorRetriever, DEFAULT_DB_DIR


def main():
    parser = argparse.ArgumentParser(description="Build COMSOL documentation knowledge base")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of PDFs to process")
    parser.add_argument("--rebuild", action="store_true", help="Clear and rebuild database")
    parser.add_argument("--pdf-dir", type=str, default=None, help="PDF directory path")
    parser.add_argument("--db-dir", type=str, default=None, help="Database directory path")
    parser.add_argument("--status", action="store_true", help="Show status only")
    parser.add_argument("--no-mirror", action="store_true", help="Don't use HuggingFace mirror")
    args = parser.parse_args()
    
    # Setup HuggingFace mirror for China
    if not args.no_mirror:
        setup_mirror()
    
    print("=" * 60)
    print("COMSOL Documentation Knowledge Base Builder")
    print("=" * 60)
    
    # Check dependencies
    print("\n[1] Checking dependencies...")
    deps = check_pdf_dependencies()
    for dep, installed in deps.items():
        status = "[OK]" if installed else "[X]"
        print(f"    {status} {dep}")
    
    if not all(deps.values()):
        print("\n[ERROR] Missing dependencies. Install with:")
        print("    pip install pymupdf chromadb sentence-transformers")
        return 1
    
    # Set paths
    pdf_dir = Path(args.pdf_dir) if args.pdf_dir else DEFAULT_PDF_DIR
    db_dir = Path(args.db_dir) if args.db_dir else DEFAULT_DB_DIR
    
    print(f"\n[2] Configuration:")
    print(f"    PDF directory: {pdf_dir}")
    print(f"    Database directory: {db_dir}")
    
    if not pdf_dir.exists():
        print(f"\n[ERROR] PDF directory not found: {pdf_dir}")
        return 1
    
    # Initialize processor
    processor = PDFProcessor(pdf_dir)
    
    # Show status only
    if args.status:
        modules = processor.get_available_modules()
        print(f"\n[3] Available modules ({len(modules)}):")
        for m in modules[:20]:
            print(f"    - {m['name']} ({m['file_count']} files)")
        if len(modules) > 20:
            print(f"    ... and {len(modules) - 20} more")
        
        # Check existing database
        retriever = VectorRetriever(pdf_dir, db_dir)
        stats = retriever.get_stats()
        print(f"\n[4] Existing knowledge base:")
        print(f"    Initialized: {stats.get('initialized', False)}")
        print(f"    Documents: {stats.get('count', 0)}")
        print(f"    Modules indexed: {stats.get('module_count', 0)}")
        return 0
    
    # List available PDFs
    pdf_files = processor.get_pdf_files()
    print(f"\n[3] Found {len(pdf_files)} PDF files")
    
    modules = processor.get_available_modules()
    print(f"    Modules: {len(modules)}")
    for m in modules[:10]:
        print(f"    - {m['name']} ({m['file_count']} files)")
    if len(modules) > 10:
        print(f"    ... and {len(modules) - 10} more")
    
    # Initialize retriever
    print(f"\n[4] Initializing vector store...")
    retriever = VectorRetriever(pdf_dir, db_dir)
    
    if args.rebuild:
        print("    Clearing existing database...")
        retriever.clear()
    
    retriever.initialize()
    
    # Process PDFs
    print(f"\n[5] Processing PDFs...")
    if args.limit:
        print(f"    Limit: {args.limit} files")
    
    stats = retriever.rebuild_from_pdfs(limit=args.limit)
    
    print(f"\n[6] Results:")
    print(f"    PDF files found: {stats.get('pdf_files_found', 0)}")
    print(f"    Chunks generated: {stats.get('chunks_generated', 0)}")
    print(f"    Chunks added: {stats.get('chunks_added', 0)}")
    print(f"    Total in database: {stats.get('final_count', 0)}")
    
    # Test search
    print(f"\n[7] Testing search...")
    results = retriever.search("electrostatic field", n_results=2)
    if results:
        print(f"    Query: 'electrostatic field'")
        print(f"    Results: {len(results)}")
        for i, r in enumerate(results):
            print(f"    [{i+1}] Module: {r.module}, Score: {r.score:.3f}")
            # Filter non-ASCII chars for Windows console compatibility
            preview = r.text[:100].encode('ascii', 'replace').decode('ascii')
            print(f"        Preview: {preview}...")
    else:
        print("    No results (this may indicate an issue)")
    
    print("\n" + "=" * 60)
    print("Knowledge base build complete!")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
