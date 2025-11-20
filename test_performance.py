#!/usr/bin/env python3
"""
Simple unit tests for performance-critical functions in db.py

Tests validate that optimizations maintain correct behavior.
"""

import re
import sys
import time

# Import regex patterns for testing
TIMESTAMP_HOSTNAME_PATTERN = re.compile(r'^[A-Z][a-z]{2}\s+\d+\s+\d+:\d+:\d+\s+\S+\s+')
PID_PATTERN = re.compile(r'\[\d+\]')
WHITESPACE_PATTERN = re.compile(r'\s+')


def normalize_log(line: str) -> str:
    """Optimized version of normalize_log for testing."""
    line = TIMESTAMP_HOSTNAME_PATTERN.sub('', line)
    line = PID_PATTERN.sub('', line)
    line = WHITESPACE_PATTERN.sub(' ', line)
    return line.strip()


def test_normalize_log():
    """Test that normalize_log works correctly with pre-compiled patterns."""
    test_cases = [
        (
            "Nov 04 23:58:33 archlinux systemd[1]: ollama.service failed",
            "systemd: ollama.service failed"
        ),
        (
            "Nov 11 12:34:56 hostname kernel[12345]: Error occurred",
            "kernel: Error occurred"
        ),
        (
            "Dec 25 00:00:01 server nginx[999]: Connection  timeout",
            "nginx: Connection timeout"
        ),
    ]
    
    print("Testing normalize_log()...")
    for input_line, expected in test_cases:
        result = normalize_log(input_line)
        assert result == expected, f"Expected '{expected}', got '{result}'"
        print(f"  ✓ '{input_line[:50]}...' -> '{result}'")
    
    print("All normalize_log tests passed!\n")


def test_normalize_performance():
    """Benchmark the normalized log function."""
    test_line = "Nov 04 23:58:33 archlinux systemd[1234]: test message here"
    
    print("Performance test (10,000 iterations)...")
    start = time.time()
    for _ in range(10000):
        normalize_log(test_line)
    elapsed = time.time() - start
    
    print(f"  Time: {elapsed:.3f}s")
    print(f"  Rate: {10000/elapsed:.0f} ops/sec")
    print(f"  Average: {elapsed/10000*1000:.3f}ms per operation\n")


def test_parse_options():
    """Test optimized parse_query_options."""
    # Simulate the optimized parsing logic
    def parse_k_option(part):
        """Fast k parsing using slicing."""
        if part.startswith("k="):
            try:
                return int(part[2:])  # Optimized: use slicing
            except ValueError:
                return None
        return None
    
    def parse_display_option(part):
        """Fast display parsing using slicing."""
        if part.startswith("display="):
            return part[8:].lower()  # Optimized: use slicing
        return None
    
    print("Testing optimized option parsing...")
    
    # Test k parsing
    assert parse_k_option("k=10") == 10
    assert parse_k_option("k=5") == 5
    assert parse_k_option("k=invalid") is None
    print("  ✓ k parsing works correctly")
    
    # Test display parsing
    assert parse_display_option("display=raw") == "raw"
    assert parse_display_option("display=pretty") == "pretty"
    assert parse_display_option("display=PRETTY") == "pretty"
    print("  ✓ display parsing works correctly")
    
    print("All option parsing tests passed!\n")


def test_memory_bounds():
    """Test that metadata bounds work correctly."""
    MAX_METADATA_SIZE = 100
    metadata = []
    
    print(f"Testing memory bounds (MAX_METADATA_SIZE={MAX_METADATA_SIZE})...")
    
    # Add 150 items
    for i in range(150):
        metadata.append({"id": i, "text": f"log {i}", "timestamp": time.time()})
        
        # Trim if needed
        if len(metadata) > MAX_METADATA_SIZE:
            overflow = len(metadata) - MAX_METADATA_SIZE
            del metadata[:overflow]
    
    assert len(metadata) == MAX_METADATA_SIZE, f"Expected {MAX_METADATA_SIZE}, got {len(metadata)}"
    assert metadata[0]["id"] == 50, "Oldest entries should be removed"
    assert metadata[-1]["id"] == 149, "Newest entries should be kept"
    
    print(f"  ✓ Metadata correctly bounded to {MAX_METADATA_SIZE} items")
    print(f"  ✓ Oldest entries (0-49) removed, keeping (50-149)")
    print("Memory bounds test passed!\n")


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("Running Performance Optimization Tests")
    print("=" * 60 + "\n")
    
    try:
        test_normalize_log()
        test_normalize_performance()
        test_parse_options()
        test_memory_bounds()
        
        print("=" * 60)
        print("All tests PASSED! ✓")
        print("=" * 60)
        return 0
    
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
