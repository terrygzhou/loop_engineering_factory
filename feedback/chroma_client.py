"""
ChromaDB client for storing and retrieving pattern embeddings.
"""
# Graceful import — chromadb may not be available locally
_chroma_error = None
try:
    import chromadb
except ImportError as e:
    _chroma_error = str(e)
    chromadb = None  # type: ignore


def get_chroma_client(url: str = None):
    """Get a ChromaDB client. Returns None if chromadb unavailable."""
    from config.loader import config as _cfg
    if chromadb is None:
        print(f"WARNING: chromadb not installed ({_chroma_error}). Pattern storage disabled.")
        return None

    if not url:
        url = _cfg.services.chroma.url

    try:
        return chromadb.HttpClient(
            host=url.split("//")[-1].split(":")[0],
            port=int(url.split(":")[-1])
        )
    except Exception as e:
        # Fallback to embedded client when no server is available
        try:
            client = chromadb.Client()
            print(f"INFO: Using embedded ChromaDB (HTTP server unavailable)")
            return client
        except Exception as embed_err:
            print(f"WARNING: Could not connect to ChromaDB: {e} (embedded fallback failed: {embed_err})")
            return None


def init_collections(client):
    """Initialize ChromaDB collections for the loop engine."""
    if client is None:
        return {}
    collections = {}
    for name in ["patterns", "feedback", "artifacts"]:
        try:
            collections[name] = client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            print(f"WARNING: Failed to init collection '{name}': {e}")
    return collections


def store_pattern(client, pattern_id: str,
                  metrics: dict, feedback: list, tags: list = None) -> bool:
    """Store a pattern in ChromaDB for future retrieval."""
    if client is None:
        return False
    try:
        collection = client.get_or_create_collection("patterns")
        embedding_text = (
            f"metrics: {metrics} "
            f"feedback: {feedback} "
            f"tags: {tags or []}"
        )
        collection.add(
            documents=[embedding_text],
            ids=[pattern_id],
            metadatas=[{"metrics": str(metrics), "tags": tags or []}],
        )
        return True
    except Exception as e:
        print(f"WARNING: Failed to store pattern '{pattern_id}': {e}")
        return False


def query_patterns(client, query_metrics: dict,
                   top_k: int = 3) -> list:
    """Query ChromaDB for similar historical patterns."""
    if client is None:
        return []
    try:
        collection = client.get_or_create_collection("patterns")
        query_text = f"metrics: {query_metrics}"
        results = collection.query(
            query_texts=[query_text],
            n_results=top_k,
        )
        patterns = []
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        dists = results.get("distances", [[]])[0]
        for i, doc in enumerate(docs):
            patterns.append({
                "document": doc,
                "metadata": metas[i] if metas else {},
                "distance": dists[i] if dists else None,
            })
        return patterns
    except Exception as e:
        print(f"WARNING: Failed to query patterns: {e}")
        return []
