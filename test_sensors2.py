import sys
import logging
from aethelnet_node.sensors import SensorArray

logging.basicConfig(level=logging.INFO)

def test():
    sensor = SensorArray()
    urls = ["https://en.wikipedia.org/wiki/Quantitative_easing"]
    chunks = sensor.crawl_web(urls, max_pages=1)
    print(f"Success! Extracted {len(chunks)} chunks.")
    if chunks:
        print(f"Content preview: {chunks[0]['content'][:100]}")

if __name__ == "__main__":
    test()
