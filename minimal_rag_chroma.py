# minimal_rag_chroma.py
import os
import argparse
import time
import chromadb
from sentence_transformers import SentenceTransformer
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- Embedding model ---
embedder = SentenceTransformer("all-MiniLM-L6-v2")

# --- File loader ---
def file_to_text(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text()
        return text

    elif ext in [".md", ".txt"]:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    else:
        raise ValueError(f"Unsupported file type: {ext}")

# --- Chunk text ---
def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50):
    words = text.split()
    chunks, start = [], 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap
    return chunks

# --- Index file into Chroma ---
def index_file(collection_name: str, file_path: str):
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return

    text = file_to_text(file_path)
    chunks = chunk_text(text)

    client = chromadb.PersistentClient(path="chroma_db")
    collection = client.get_or_create_collection(name=collection_name)

    embeddings = embedder.encode(chunks).tolist()
    ids = [f"{os.path.basename(file_path)}_{i}" for i in range(len(chunks))]

    # Remove old docs with same prefix
    try:
        collection.delete(ids=ids)
    except Exception:
        pass

    collection.add(documents=chunks, embeddings=embeddings, ids=ids)
    print(f"✅ Indexed {len(chunks)} chunks from {file_path} into collection '{collection_name}'.")

# --- Query Chroma ---
def query_collection(collection_name: str, query: str, top_k: int = 5):
    client = chromadb.PersistentClient(path="chroma_db")
    collection = client.get_or_create_collection(name=collection_name)

    q_emb = embedder.encode([query]).tolist()
    results = collection.query(query_embeddings=q_emb, n_results=top_k)

    print("\n🔎 Query Results:")
    for i, doc in enumerate(results["documents"][0]):
        print(f"\nResult {i+1}: {doc}")

# --- Watchdog for auto-reindex ---
class FileChangeHandler(FileSystemEventHandler):
    def __init__(self, collection_name, file_path):
        self.collection_name = collection_name
        self.file_path = file_path

    def on_modified(self, event):
        if event.src_path.replace("/", "\\") == self.file_path.replace("/", "\\"):
            print(f"\n🔄 Detected change in {self.file_path}, re-indexing...")
            index_file(self.collection_name, self.file_path)

# --- Main ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=str, help="Path to file (PDF/MD/TXT) to index")
    parser.add_argument("--query", type=str, help="Query to ask")
    parser.add_argument("--collection", type=str, required=True, help="Collection name")
    parser.add_argument("--topk", type=int, default=5, help="Number of results")
    parser.add_argument("--watch", action="store_true", help="Watch file for changes")
    args = parser.parse_args()

    if args.index:
        index_file(args.collection, args.index)

    if args.query:
        query_collection(args.collection, args.query, args.topk)

    if args.watch and args.index:
        event_handler = FileChangeHandler(args.collection, args.index)
        observer = Observer()
        observer.schedule(event_handler, path=os.path.dirname(args.index) or ".", recursive=False)
        observer.start()
        print(f"👀 Watching {args.index} for changes. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
