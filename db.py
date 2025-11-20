#!/usr/bin/env python3
"""
Live Log Embedding System (journalctl -> FAISS)

Features:
 - Streams `journalctl -f`
 - Deduplicates repeated messages by normalizing lines (strips timestamps, PIDs)
 - Summarizes frequent repeats every 10s as "⏱ … repeated Nx"
 - Embeds logs in real time with SentenceTransformer + FAISS
 - Search with adjustable k and display mode
"""

import re
import sys
import queue
import threading
import subprocess
import time
from datetime import datetime
from collections import deque

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer

# Configuration
JOURNALCTL_CMD = ["journalctl", "-f", "-o", "short"]
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
EMBED_DIM = 384
BATCH_SIZE = 16
DEFAULT_K = 5
FLUSH_INTERVAL = 10  # seconds between repeated-log summaries
MAX_METADATA_SIZE = 100000  # Maximum number of logs to keep in memory

# Global state
log_queue = queue.Queue()
metadata = []  # list of {"id": int, "text": str, "timestamp": float}
metadata_lock = threading.Lock()
index = None
model = None

# Repeat detection cache
repeat_cache = {}  # {normalized_message: count}
cache_lock = threading.Lock()

# Shutdown event
shutdown_event = threading.Event()

# Pre-compiled regex patterns for normalize_log
TIMESTAMP_HOSTNAME_PATTERN = re.compile(r'^[A-Z][a-z]{2}\s+\d+\s+\d+:\d+:\d+\s+\S+\s+')
PID_PATTERN = re.compile(r'\[\d+\]')
WHITESPACE_PATTERN = re.compile(r'\s+')


def normalize_log(line: str) -> str:
    """
    Strip volatile fields (timestamps, PIDs, hostnames) for repeat detection.
    
    Transforms:
      "Nov 04 23:58:33 archlinux systemd[1]: ollama.service failed"
    Into:
      "systemd: ollama.service failed"
    
    This allows detection of identical log messages that only differ in
    timestamp, hostname, or process ID.
    
    Optimized to use pre-compiled regex patterns for better performance.
    """
    # Remove leading timestamp (e.g., "Nov 04 23:58:33") and hostname
    line = TIMESTAMP_HOSTNAME_PATTERN.sub('', line)
    
    # Remove PID markers like [1234]
    line = PID_PATTERN.sub('', line)
    
    # Normalize multiple spaces to single space
    line = WHITESPACE_PATTERN.sub(' ', line)
    
    return line.strip()


def watch_journalctl():
    """
    Stream logs from journalctl in real-time.
    
    Runs journalctl -f and normalizes each log line for deduplication.
    Stores normalized logs in the repeat cache for batch processing.
    
    Optimized with better subprocess handling and reduced locking overhead.
    """
    proc = None
    try:
        proc = subprocess.Popen(
            JOURNALCTL_CMD,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        while not shutdown_event.is_set():
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    # Process has terminated
                    break
                continue
            
            line = line.rstrip("\n")
            if not line:
                continue
            
            normalized = normalize_log(line)
            if normalized:
                # Optimize cache access by only locking when necessary
                with cache_lock:
                    # Use get with default to avoid KeyError
                    repeat_cache[normalized] = repeat_cache.get(normalized, 0) + 1
    
    except Exception as e:
        print(f"Error in journalctl watcher: {e}", file=sys.stderr)
    
    finally:
        if proc:
            # Ensure proper cleanup
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()  # Wait for kill to complete


def repeat_flusher():
    """
    Periodically flush cached log entries to the embedding queue.
    
    Every FLUSH_INTERVAL seconds, this function takes all accumulated
    log messages and either:
    - Sends single occurrences as-is
    - Summarizes repeated messages as "⏱ timestamp | message repeated Nx"
    
    Optimized to reduce string formatting and unnecessary operations.
    """
    next_id = 0
    
    while not shutdown_event.is_set():
        # Use shutdown-aware sleep
        if shutdown_event.wait(timeout=FLUSH_INTERVAL):
            break
        
        # Cache timestamp string to avoid repeated formatting
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        current_ts = time.time()
        
        # Atomically extract and clear cache
        with cache_lock:
            if not repeat_cache:
                continue
            items = list(repeat_cache.items())
            repeat_cache.clear()
        
        # Process cached entries
        for msg, count in items:
            if not msg:
                continue
            
            if count == 1:
                # Single occurrence - no summarization needed
                log_queue.put((next_id, msg, current_ts))
            else:
                # Multiple occurrences - create summary
                summary = f'⏱ {now} | "{msg}" repeated {count}x'
                log_queue.put((next_id, summary, current_ts))
            
            next_id += 1
    
    # Final flush on shutdown
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with cache_lock:
        items = list(repeat_cache.items())
        repeat_cache.clear()
    
    for msg, count in items:
        if msg:
            ts = time.time()
            summary = f'⏱ {now} | "{msg}" repeated {count}x' if count > 1 else msg
            log_queue.put((next_id, summary, ts))
            next_id += 1


def embed_worker():
    """
    Process log entries from the queue: embed them and add to FAISS index.
    
    Batches logs for efficient embedding, then adds them to the FAISS index
    along with their metadata. Handles graceful shutdown with final batch flush.
    
    Optimized to avoid unnecessary batch processing when empty.
    """
    batch_ids = []
    batch_texts = []
    batch_timestamps = []
    
    def process_batch():
        """Helper to embed and index a batch of logs."""
        if not batch_texts:
            return
        
        try:
            embeddings = model.encode(batch_texts, convert_to_numpy=True)
            index.add(embeddings)
            
            # Update metadata with thread safety
            with metadata_lock:
                # Implement circular buffer for metadata to prevent unbounded growth
                for i, txt, tstamp in zip(batch_ids, batch_texts, batch_timestamps):
                    metadata.append({"id": i, "text": txt, "timestamp": tstamp})
                
                # Trim metadata if it exceeds maximum size
                if len(metadata) > MAX_METADATA_SIZE:
                    # Remove oldest entries
                    overflow = len(metadata) - MAX_METADATA_SIZE
                    del metadata[:overflow]
        
        except Exception as e:
            print(f"Error processing batch: {e}", file=sys.stderr)
        
        finally:
            batch_ids.clear()
            batch_texts.clear()
            batch_timestamps.clear()
    
    while not shutdown_event.is_set():
        try:
            # Use longer timeout to reduce CPU wake-ups
            _id, text, ts = log_queue.get(timeout=2.0)
        except queue.Empty:
            # Flush partial batch if any (skip if empty)
            if batch_texts:
                process_batch()
            continue
        
        # Add to batch
        batch_ids.append(_id)
        batch_texts.append(text)
        batch_timestamps.append(ts)
        
        # Process when batch is full
        if len(batch_texts) >= BATCH_SIZE:
            process_batch()
    
    # Final flush on shutdown
    if batch_texts:
        process_batch()


def search_query(q: str, k: int, display_mode: str):
    """
    Search the FAISS index for logs similar to the query.
    
    Args:
        q: Search query string
        k: Number of top results to return
        display_mode: "raw" for text only, "pretty" for formatted output
    
    Returns:
        List of matching log entries
    
    Optimized with early validation and efficient metadata access.
    """
    # Validate input early
    if not q or not q.strip():
        return ["Empty query provided."]
    
    if k <= 0:
        return ["Invalid k value. Must be positive."]
    
    try:
        # Generate query embedding
        q_emb = model.encode([q.strip()], convert_to_numpy=True)
        
        # Search FAISS index
        with metadata_lock:
            if index.ntotal == 0:
                return ["No logs indexed yet. Please wait for data to accumulate."]
            
            # Adjust k to not exceed available entries
            k_adjusted = min(k, index.ntotal)
            D, I = index.search(q_emb, k_adjusted)
            
            # Pre-compute metadata length for bounds checking
            meta_len = len(metadata)
            results = []
            
            for dist, idx in zip(D[0], I[0]):
                # FAISS returns -1 for invalid indices
                if idx < 0 or idx >= meta_len:
                    continue
                
                meta = metadata[idx]
                if display_mode == "raw":
                    results.append(meta["text"])
                else:
                    results.append(
                        f"{meta['timestamp']:.3f} | dist={dist:.3f} | {meta['text']}"
                    )
        
        return results if results else ["No matching results found."]
    
    except Exception as e:
        return [f"Search error: {e}"]


def initialize_models():
    """
    Initialize the SentenceTransformer model and FAISS index.
    
    Returns:
        Tuple of (model, index) or (None, None) if initialization fails
    """
    try:
        print("Loading embedding model...")
        model_instance = SentenceTransformer(EMBED_MODEL_NAME)
        index_instance = faiss.IndexFlatL2(EMBED_DIM)
        print("Model loaded successfully.")
        return model_instance, index_instance
    except Exception as e:
        print(f"Failed to initialize models: {e}", file=sys.stderr)
        return None, None


def parse_query_options(line: str):
    """
    Parse search query and extract options like k and display mode.
    
    Args:
        line: User input string
    
    Returns:
        Tuple of (query_text, k, display_mode)
    
    Optimized to minimize string operations and provide better validation.
    """
    k = DEFAULT_K
    display_mode = "pretty"
    parts = line.split()
    filtered_parts = []
    
    for part in parts:
        if part.startswith("k="):
            try:
                k_val = int(part[2:])  # Faster than split
                if k_val > 0:
                    k = k_val
                else:
                    print("Warning: k must be positive; using default.")
                    k = DEFAULT_K
            except ValueError:
                print("Warning: Invalid k value; using default.")
        
        elif part.startswith("display="):
            mode = part[8:].lower()  # Faster than split
            if mode in ("raw", "pretty"):
                display_mode = mode
            else:
                print(f"Warning: Invalid display mode '{mode}'; using pretty.")
        
        else:
            filtered_parts.append(part)
    
    query_text = " ".join(filtered_parts)
    return query_text, k, display_mode


def main():
    """
    Main entry point: initialize system, start background threads, handle user queries.
    """
    global model, index
    
    # Initialize models
    model, index = initialize_models()
    if model is None or index is None:
        print("Cannot start system without models. Exiting.")
        return 1
    
    # Start background threads
    watcher_thread = threading.Thread(target=watch_journalctl, daemon=True)
    flusher_thread = threading.Thread(target=repeat_flusher, daemon=True)
    embed_thread = threading.Thread(target=embed_worker, daemon=True)
    
    watcher_thread.start()
    flusher_thread.start()
    embed_thread.start()
    
    print("🧠 Live log embedding system started (journalctl + deduplication).")
    print("Collecting initial logs...")
    time.sleep(5)
    print("Ready for queries. Type 'exit' or 'quit' to stop.\n")
    
    # Main interaction loop
    try:
        while True:
            try:
                line = input("Enter search query (or 'exit' to quit): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nExiting...")
                break
            
            if not line:
                continue
            
            if line.lower() in ("exit", "quit"):
                print("Exiting...")
                break
            
            # Parse query and options
            query_text, k, display_mode = parse_query_options(line)
            
            if not query_text:
                print("Empty query text; please provide a search term.")
                continue
            
            # Execute search
            hits = search_query(query_text, k, display_mode)
            
            # Display results
            print("-" * 80)
            print(f"Top {k} results (display={display_mode}):")
            for result in hits:
                print(result)
            print("-" * 80)
            print()
    
    finally:
        # Graceful shutdown
        print("Shutting down background threads...")
        shutdown_event.set()
        
        # Give threads time to finish
        watcher_thread.join(timeout=2)
        flusher_thread.join(timeout=2)
        embed_thread.join(timeout=2)
        
        print("Shutdown complete.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())