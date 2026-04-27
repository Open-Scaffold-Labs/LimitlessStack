#!/usr/bin/env python3.11
"""
Semantic search over the OpenScaffold Pinecone index.

Three namespaces are available:
    repos     source code + docs from raw/openscaffold-repos/*
    wiki      curated wiki pages (wiki/**/*.md + CLAUDE.md, README.md)
    uploads   attachments from raw/uploads/**

By default, searches all three and merges by score.

Usage:
    python3.11 tools/pinecone-search.py "where do we handle JWT refresh"
    python3.11 tools/pinecone-search.py "how does limitless stack work" --namespace wiki
    python3.11 tools/pinecone-search.py "..." --repo FireHazmat
    python3.11 tools/pinecone-search.py "..." --namespace repos --top 3
"""
import argparse
import subprocess

INDEX_NAME = "openscaffold"
ALL_NAMESPACES = ("repos", "wiki", "uploads")


def get_api_key() -> str:
    return subprocess.run(
        ["security", "find-generic-password", "-s", "pinecone-api-key", "-w"],
        capture_output=True, text=True, check=True
    ).stdout.strip()


def search_namespace(index, namespace: str, query: str, top: int, repo_filter: str | None):
    search_kwargs = {
        "namespace": namespace,
        "query": {"top_k": top, "inputs": {"text": query}},
        "fields": ["corpus", "repo", "path", "bucket", "scope", "chunk_index", "chunk_text", "ext"],
    }
    if repo_filter and namespace == "repos":
        search_kwargs["query"]["filter"] = {"repo": {"$eq": repo_filter}}
    elif repo_filter and namespace != "repos":
        return []  # repo filter only applies to the repos namespace
    try:
        results = index.search(**search_kwargs)
    except Exception as e:
        print(f"  [{namespace}] search failed: {e}")
        return []
    out = []
    for hit in results.result.hits:
        f = hit.fields
        score = hit._score if hasattr(hit, "_score") else hit.score
        out.append((score, namespace, f))
    return out


def format_hit(score: float, namespace: str, f: dict) -> tuple[str, str]:
    """Return (header, snippet) lines."""
    snippet = (f.get("chunk_text") or "")[:200].replace("\n", " ")
    path = f.get("path", "?")
    chunk = f.get("chunk_index")
    if namespace == "repos":
        loc = f"{f.get('repo', '?')}/{path}"
    elif namespace == "wiki":
        bucket = f.get("bucket")
        loc = f"wiki/{path}" if bucket != "root" else path
    elif namespace == "uploads":
        loc = f"uploads/{path}"
    else:
        loc = f"{namespace}:{path}"
    header = f"  [{score:.3f}]  [{namespace}] {loc}  (chunk {chunk})"
    return header, f"           {snippet}…"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="natural-language search query")
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--repo", help="filter to a single repo (only applies to repos namespace)")
    parser.add_argument("--namespace", default="all",
                        help="namespace to search: repos|wiki|uploads|all (default: all)")
    args = parser.parse_args()

    from pinecone import Pinecone
    pc = Pinecone(api_key=get_api_key())
    index = pc.Index(INDEX_NAME)

    if args.namespace == "all":
        namespaces = ALL_NAMESPACES
        # When searching across all namespaces, fetch top N from each then merge.
        per_ns_top = args.top
    else:
        namespaces = (args.namespace,)
        per_ns_top = args.top

    all_hits: list = []
    for ns in namespaces:
        all_hits.extend(search_namespace(index, ns, args.query, per_ns_top, args.repo))

    # Merge by score descending, then truncate to --top.
    all_hits.sort(key=lambda x: x[0], reverse=True)
    all_hits = all_hits[: args.top]

    print(f"\nQuery: {args.query}")
    if args.namespace != "all":
        print(f"Namespace: {args.namespace}")
    else:
        print(f"Namespaces: {', '.join(namespaces)}")
    if args.repo:
        print(f"Filter: repo={args.repo}")
    print(f"Top {args.top} hits:\n")

    for score, ns, f in all_hits:
        header, snippet = format_hit(score, ns, f)
        print(header)
        print(snippet)
        print()


if __name__ == "__main__":
    main()
