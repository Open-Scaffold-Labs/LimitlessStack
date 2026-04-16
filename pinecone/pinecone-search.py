#!/usr/bin/env python3.11
"""
Semantic search over the OpenScaffold Pinecone index.

Usage:
    python3.11 tools/pinecone-search.py "where do we handle JWT refresh"
    python3.11 tools/pinecone-search.py "how is the iPad split-pane laid out" --top 3
    python3.11 tools/pinecone-search.py "..." --repo FireHazmat
"""
import argparse
import subprocess


def get_api_key() -> str:
    return subprocess.run(
        ["security", "find-generic-password", "-s", "pinecone-api-key", "-w"],
        capture_output=True, text=True, check=True
    ).stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="natural-language search query")
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--repo", help="filter to a single repo")
    parser.add_argument("--namespace", default="repos")
    args = parser.parse_args()

    from pinecone import Pinecone
    pc = Pinecone(api_key=get_api_key())
    index = pc.Index("openscaffold")

    search_kwargs = {
        "namespace": args.namespace,
        "query": {"top_k": args.top, "inputs": {"text": args.query}},
        "fields": ["repo", "path", "chunk_index", "chunk_text"],
    }
    if args.repo:
        search_kwargs["query"]["filter"] = {"repo": {"$eq": args.repo}}

    results = index.search(**search_kwargs)

    print(f"\nQuery: {args.query}")
    if args.repo:
        print(f"Filter: repo={args.repo}")
    print(f"Top {args.top} hits:\n")
    for hit in results.result.hits:
        f = hit.fields
        score = hit._score if hasattr(hit, "_score") else hit.score
        snippet = (f.get("chunk_text") or "")[:200].replace("\n", " ")
        print(f"  [{score:.3f}]  {f['repo']}/{f['path']}  (chunk {f.get('chunk_index')})")
        print(f"           {snippet}…\n")


if __name__ == "__main__":
    main()
