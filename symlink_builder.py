import os
import sys
import argparse

INGEST_ZONE = os.path.expanduser("~/.aethelnet/ingest_zone")

def setup_zone():
    if not os.path.exists(INGEST_ZONE):
        os.makedirs(INGEST_ZONE)
        print(f"Created secure ingest sandbox at: {INGEST_ZONE}")

def build_symlink(target_path, alias_name):
    target = os.path.abspath(os.path.expanduser(target_path))
    if not os.path.exists(target):
        print(f"Error: Target path '{target}' does not exist.")
        sys.exit(1)
        
    link_path = os.path.join(INGEST_ZONE, alias_name)
    
    if os.path.exists(link_path):
        print(f"Warning: Alias '{alias_name}' already exists in ingest zone.")
        return
        
    os.symlink(target, link_path)
    print(f"Success: Granted node access to '{target}' via alias '{alias_name}'")

if __name__ == "__main__":
    setup_zone()
    
    parser = argparse.ArgumentParser(description="Aethelnet Privacy-Aware Symlink Builder")
    parser.add_argument("target", help="The absolute or relative path to the directory you want to ingest")
    parser.add_argument("alias", help="A safe name for this link inside the sandbox (e.g., 'Music', 'Docs')")
    
    args = parser.parse_args()
    build_symlink(args.target, args.alias)
