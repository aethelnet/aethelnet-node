import sys
import logging
from aethelnet_node.sensors import SensorArray

logging.basicConfig(level=logging.INFO)

def test():
    print("Testing SensorArray.crawl_web...")
    sensor = SensorArray()
    urls = ["https://en.wikipedia.org/wiki/Complexity_theory"]
    try:
        chunks = sensor.crawl_web(urls, max_pages=1)
        print(f"Success! Extracted {len(chunks)} chunks.")
        if chunks:
            print(f"Sample type: {chunks[0]['type']}")
            print(f"Sample content length: {len(chunks[0]['content'])}")
    except Exception as e:
        print(f"Failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    test()
