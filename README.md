# 🧠 Live Log Embedding System (journalctl → FAISS)

A real-time Linux log monitoring and semantic search tool that streams logs from `journalctl`, deduplicates repeated entries, embeds them using SentenceTransformer, and indexes them with FAISS for fast similarity search.

📖 **[View Applications & Use Cases](./APPLICATIONS.md)** — Comprehensive guide to Kernolog's applications in system administration, security, DevOps, and more.

---

## 🚀 Features

* **Real-time log streaming:** Follows live logs with `journalctl -f`.
* **Smart deduplication:** Strips volatile fields (timestamps, PIDs, hostnames) for repeat detection.
* **Batch summarization:** Groups frequent identical messages every 10 seconds into compact summaries like
  `⏱ 2025-11-11 | "systemd: service failed" repeated 42x`.
* **Vector embeddings:** Converts logs into semantic embeddings using `all-MiniLM-L6-v2`.
* **FAISS indexing:** Enables fast similarity search across all stored logs.
* **Interactive search:** Query logs with natural language and adjustable top-K (`k=5`, `k=10`, etc.).
* **Multithreaded:** Separate threads for log ingestion, deduplication, embedding, and indexing.

---

## 🧩 Tech Stack

| Component                                     | Purpose                               |
| --------------------------------------------- | ------------------------------------- |
| **Python 3.9+**                               | Core runtime                          |
| **journalctl**                                | Log streaming                         |
| **SentenceTransformers (`all-MiniLM-L6-v2`)** | Text embedding                        |
| **FAISS**                                     | Vector indexing and similarity search |
| **threading / queue**                         | Concurrent processing pipeline        |

---

## ⚙️ Installation

1. **Clone this repository**

   ```bash
   git clone https://github.com/Tonystank2/Kernolog
   cd Kernolog
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Run the system**

   ```bash
   python3 db.py
   ```

---

## 🔍 Usage

When running, the system automatically:

* Streams system logs via `journalctl -f`
* Deduplicates repeated messages
* Generates embeddings and stores them in a FAISS index

You can then query interactively:

```bash
Enter search query (or 'exit' to quit): failed service restart k=10 display=pretty
```

### Options

| Parameter        | Description                                      | Example       |
| ---------------- | ------------------------------------------------ | ------------- |
| `k=<N>`          | Number of top results to display                 | `k=10`        |
| `display=raw`    | Show only log text                               | `display=raw` |
| `display=pretty` | Show timestamps, distances, and formatted output | *(default)*   |

---

## 🧠 Example Output

```
--------------------------------------------------------------------------------
Top 5 results (display=pretty):
1731327900.231 | dist=0.121 | systemd: ollama.service failed
1731327902.481 | dist=0.188 | ⏱ 2025-11-11 | "systemd: ollama.service failed" repeated 3x
1731327908.912 | dist=0.223 | systemd: docker.service stopped
--------------------------------------------------------------------------------
```

---

## 🧰 Configuration

You can tweak parameters directly in `db.py`:

| Variable           | Default            | Description                      |
| ------------------ | ------------------ | -------------------------------- |
| `EMBED_MODEL_NAME` | `all-MiniLM-L6-v2` | SentenceTransformer model        |
| `BATCH_SIZE`       | `16`               | Embedding batch size             |
| `DEFAULT_K`        | `5`                | Default number of search results |
| `FLUSH_INTERVAL`   | `10`               | Seconds between repeat summaries |

---

## 🧑‍💻 Architecture Overview

```text
┌────────────────────┐
│ journalctl -f      │  ← stream logs
└─────────┬──────────┘
          │
          ▼
  normalize_log() ──► repeat_cache ──► repeat_flusher()
          │                             │
          ▼                             ▼
       log_queue ────────────────► embed_worker() ──► FAISS index
                                         │
                                         ▼
                                   search_query()
```

---

## 📚 Documentation

* **[APPLICATIONS.md](./APPLICATIONS.md)** — Comprehensive guide to use cases, applications, and integration scenarios
* **[testing.md](./testing.md)** — Complete testing guide with examples
* **[CONTRIBUTING.md](./CONTRIBUTING.md)** — How to contribute to the project

---

## 🧾 License

This project is licensed under the **GNU General Public License v3.0 (GPLv3)** — see the [LICENSE](./LICENSE) file for details.

> You are free to use, modify, and distribute this software,
> provided that any derivative works are also released under the GPL.

---

## 🤝 Contributing

Pull requests are welcome!
If you make improvements or find issues, please open an issue or PR.
All contributions must comply with the GPLv3 license.

---

## 💬 Acknowledgments

* [SentenceTransformers](https://www.sbert.net/)
* [FAISS](https://faiss.ai/)
* [Systemd journalctl](https://man7.org/linux/man-pages/man1/journalctl.1.html)

---

**Author:** Rithik A Nair
**Year:** 2025
🧠 *Built for live semantic log exploration.*
