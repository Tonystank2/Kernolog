# Testing Guide for Kernolog

This guide provides comprehensive instructions for testing the Live Log Embedding System on Linux. macOS-specific notes are included where applicable.

---

## Prerequisites

### System Requirements

- **Linux:** Any modern distribution with systemd (Ubuntu 20.04+, Fedora, Arch, Debian, etc.)
- **Python:** 3.9 or higher
- **Memory:** At least 2GB RAM (for embedding model)
- **Disk Space:** ~500MB for model and dependencies

### Required Tools

- `journalctl` (part of systemd)
- `pip` (Python package manager)
- Internet connection (for initial model download)

---

## Installation and Setup

### 1. Clone the Repository

```bash
git clone https://github.com/Tonystank2/Kernolog
cd Kernolog
```

### 2. Create Virtual Environment (Recommended)

```bash
python3 -m venv venv
source venv/bin/activate  # On Linux
```

**macOS Note:** The command is the same on macOS.

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

**Expected output:**
- Installation of `faiss-cpu`, `sentence-transformers`, `numpy`, and their dependencies
- First-time model download (~80MB for `all-MiniLM-L6-v2`)

### 4. Verify Installation

```bash
python3 -c "import faiss; import sentence_transformers; print('Dependencies OK')"
```

---

## Basic Testing

### Test 1: Check journalctl Access

Verify you can access system logs:

```bash
journalctl -n 20 -o short
```

**Expected:** Last 20 log entries displayed.

**If permission denied:**
```bash
# Option 1: Add user to systemd-journal group
sudo usermod -aG systemd-journal $USER
# Then log out and back in

# Option 2: Run with sudo (not recommended for production)
sudo python3 db.py
```

**macOS Note:** macOS does not use systemd/journalctl. This tool is designed for Linux only. See the macOS Testing section below for alternatives.

---

### Test 2: Start the System

```bash
python3 db.py
```

**Expected output:**
```
Loading embedding model...
Model loaded successfully.
🧠 Live log embedding system started (journalctl + deduplication).
Collecting initial logs...
Ready for queries. Type 'exit' or 'quit' to stop.

Enter search query (or 'exit' to quit):
```

**First run:** Model download may take 1-2 minutes. Subsequent runs are instant.

---

### Test 3: Generate Test Logs

While `db.py` is running, open a new terminal and generate some test logs:

```bash
# Terminal 2
logger "Test message: service started successfully"
logger "Test message: authentication failed"
logger "Test message: connection timeout error"
logger "Test message: database query completed"
logger "Test message: service started successfully"  # Repeat
```

**Wait 10-15 seconds** for the flush interval to process these logs.

---

### Test 4: Basic Search Query

In the `db.py` terminal, try a simple search:

```
Enter search query (or 'exit' to quit): service started
```

**Expected output:**
```
--------------------------------------------------------------------------------
Top 5 results (display=pretty):
1731327900.123 | dist=0.089 | Test message: service started successfully
1731327905.456 | dist=0.234 | ⏱ 2025-11-13 16:45:10 | "Test message: service started successfully" repeated 2x
--------------------------------------------------------------------------------
```

**Explanation:**
- `dist` = Distance score (lower = better match)
- Repeated messages are summarized
- Timestamps show when logs were captured

---

### Test 5: Advanced Search Options

#### Test 5a: Change Number of Results

```
Enter search query (or 'exit' to quit): error k=10
```

**Expected:** Up to 10 results related to "error"

#### Test 5b: Raw Display Mode

```
Enter search query (or 'exit' to quit): authentication display=raw
```

**Expected:** Only log text, no timestamps or distances

#### Test 5c: Combined Options

```
Enter search query (or 'exit' to quit): timeout k=3 display=pretty
```

**Expected:** Top 3 results with full formatting

---

## Functional Testing

### Test 6: Deduplication Verification

Generate repeated logs:

```bash
# Terminal 2
for i in {1..50}; do logger "Repeated test message $((i % 5))"; done
```

**Expected behavior:**
- Similar messages grouped together
- Summary lines like `"Repeated test message 1" repeated 10x`

---

### Test 7: Real-time Streaming

Monitor live system activity:

```bash
# Terminal 2 - Generate continuous logs
while true; do logger "Continuous log entry $(date +%s)"; sleep 2; done
```

Then search in db.py:

```
Enter search query (or 'exit' to quit): continuous
```

**Expected:** New entries appear in search results as they're indexed

Stop the log generator with `Ctrl+C` in Terminal 2.

---

### Test 8: Semantic Search

Test the semantic understanding:

```bash
# Generate various logs
logger "Database connection failed with error code 500"
logger "Unable to establish database link"
logger "File system is running out of space"
logger "Disk usage critical alert"
```

Search with related terms:

```
Enter search query (or 'exit' to quit): database problem
```

**Expected:** Both "connection failed" and "unable to establish" entries appear (semantic similarity)

```
Enter search query (or 'exit' to quit): disk full
```

**Expected:** Both "out of space" and "usage critical" entries appear

---

### Test 9: Empty Index Handling

Restart the system and immediately search:

```bash
python3 db.py
# Immediately after "Ready for queries" appears:
Enter search query (or 'exit' to quit): test
```

**Expected:** Message indicating no logs are indexed yet

---

### Test 10: Graceful Shutdown

Test clean exit:

```bash
# Method 1: Type exit
Enter search query (or 'exit' to quit): exit

# Method 2: Ctrl+C
Enter search query (or 'exit' to quit): ^C
```

**Expected output:**
```
Exiting...
Shutting down background threads...
Shutdown complete.
```

---

## Performance Testing

### Test 11: High Volume Logs

Generate a large number of logs:

```bash
# Terminal 2
for i in {1..1000}; do logger "Load test message variant $((RANDOM % 100))"; done
```

**Monitor:**
- System should remain responsive
- Memory usage should be stable
- Search results should still be fast (<1 second)

Check resource usage:

```bash
# Terminal 3
ps aux | grep db.py
```

**Expected:** Memory usage between 500MB-1GB depending on log volume

---

### Test 12: Search Performance

Test search with large index:

```bash
time python3 -c "
import sys
sys.path.insert(0, '.')
# Would need to modify db.py to expose search as importable function
# For manual testing, just note search response times in interactive mode
"
```

**Expected:** Search results in <1 second even with 10,000+ indexed logs

---

## Error Handling Testing

### Test 13: Invalid Input Handling

Test various invalid inputs:

```
Enter search query (or 'exit' to quit): test k=invalid
```

**Expected:** Warning about invalid k, uses default

```
Enter search query (or 'exit' to quit): test display=wrong
```

**Expected:** Warning about invalid display mode, uses pretty

```
Enter search query (or 'exit' to quit): test k=-5
```

**Expected:** Warning about positive k required, uses default

```
Enter search query (or 'exit' to quit): k=10
```

**Expected:** Warning about empty query text

---

### Test 14: Permission Issues

Test without proper permissions:

```bash
# Remove from group if you added yourself earlier
sudo gpasswd -d $USER systemd-journal
# Log out and back in, then:
python3 db.py
```

**Expected:** Error message about journalctl access failure

**Fix:**
```bash
sudo usermod -aG systemd-journal $USER
# Log out and back in
```

---

## Stress Testing

### Test 15: Rapid Log Generation

```bash
# Terminal 2
for i in {1..5000}; do logger "Stress test $i"; done &
```

**Observe:**
- No crashes
- Logs eventually indexed
- System remains queryable

---

### Test 16: Long-running Stability

Leave the system running for extended period:

```bash
python3 db.py &
PID=$!

# Check after 1 hour
sleep 3600
ps -p $PID  # Should still be running

# Search should still work
fg  # Bring to foreground
# Test a query
```

---

## Integration Testing

### Test 17: Real System Logs

Search for actual system events:

```
Enter search query (or 'exit' to quit): systemd service failed k=10
```

**Expected:** Real failed service entries (if any exist in logs)

```
Enter search query (or 'exit' to quit): authentication success
```

**Expected:** SSH logins, sudo commands, etc.

```
Enter search query (or 'exit' to quit): kernel error
```

**Expected:** Kernel-level error messages (if any)

---

**Note:** These modifications are for testing purposes only. The production version should remain Linux-specific.

---

## Troubleshooting

### Issue: "Failed to initialize models"

**Cause:** Missing dependencies or network issues during model download

**Solution:**
```bash
pip install --upgrade sentence-transformers faiss-cpu
# Verify internet connection
curl -I https://huggingface.co
```

---

### Issue: "No logs indexed yet"

**Cause:** Not enough time elapsed or no logs generated

**Solution:**
- Wait 10-15 seconds after startup
- Generate test logs with `logger "test message"`
- Check if journalctl is producing output: `journalctl -f`

---

### Issue: High Memory Usage

**Cause:** Large number of logs indexed

**Solution:** This is expected behavior. The embedding model and FAISS index consume memory.
- Monitor with: `top -p $(pgrep -f db.py)`
- Typical usage: 500MB-2GB depending on log volume

---

### Issue: "Error in journalctl watcher"

**Cause:** journalctl command failed or permission denied

**Solution:**
```bash
# Test journalctl directly
journalctl -f -o short
# If fails, check permissions
groups | grep systemd-journal
```

---

## Verification Checklist

After testing, verify:

- [ ] System starts without errors
- [ ] Logs are captured and deduplicated
- [ ] Repeated messages are summarized correctly
- [ ] Search returns relevant results
- [ ] Semantic search works (similar terms match)
- [ ] Custom k values work
- [ ] Both display modes (raw/pretty) work
- [ ] System handles invalid input gracefully
- [ ] Graceful shutdown works (exit, Ctrl+C)
- [ ] No resource leaks during extended operation
- [ ] Real system logs are searchable

---

## Test Results Documentation

When reporting test results, include:

```
Environment:
- OS: [Ubuntu 22.04, Fedora 39, etc.]
- Python version: [3.9.x, 3.11.x, etc.]
- RAM: [Amount]
- CPU: [Model]

Test Results:
- [✓/✗] Basic functionality
- [✓/✗] Deduplication
- [✓/✗] Semantic search
- [✓/✗] Performance (under load)
- [✓/✗] Graceful shutdown
- [✓/✗] Error handling

Issues Found:
[Describe any problems encountered]

Notes:
[Additional observations]
```

---

## Automated Testing (Future)

For future test automation, consider:

```bash
#!/bin/bash
# test_suite.sh

echo "Testing Kernolog..."

# Start system in background
python3 db.py &
PID=$!
sleep 10

# Generate test logs
for i in {1..100}; do
  logger "Automated test message $i"
done

sleep 15

# Test query via stdin
echo "test" | timeout 5 python3 -c "
import sys
sys.path.insert(0, '.')
# Query testing code here
"

# Cleanup
kill $PID
wait $PID 2>/dev/null

echo "Tests complete"
```

---

## Support

If you encounter issues during testing:

1. Check the [GitHub Issues](https://github.com/Tonystank2/Kernolog/issues)
2. Review error messages in terminal
3. Verify all prerequisites are met
4. Open a new issue with test results and error logs

---

**Happy Testing! 🧠**
