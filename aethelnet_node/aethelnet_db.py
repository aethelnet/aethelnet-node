import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(__file__), 'aethelnet.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Nodes Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT,
            universe_id TEXT,
            label TEXT,
            content TEXT,
            x REAL,
            y REAL,
            z REAL,
            is_expanded INTEGER,
            agent_type TEXT,
            image_url TEXT,
            inherited_from_id TEXT,
            inherited_index INTEGER,
            has_manual_title INTEGER,
            is_public INTEGER DEFAULT 0,
            system_module TEXT,
            manual_width REAL,
            manual_height REAL,
            PRIMARY KEY (id, universe_id)
        )
    ''')
    # Edges Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS edges (
            universe_id TEXT,
            source TEXT,
            target TEXT,
            weight REAL,
            UNIQUE(universe_id, source, target)
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_nodes_public ON nodes(is_public)')
    
    conn.commit()
    conn.close()

def load_graph():
    conn = get_db()
    
    universe_map = {}
    
    for row in conn.execute('SELECT * FROM nodes'):
        u_id = row['universe_id']
        if u_id not in universe_map:
            universe_map[u_id] = {'nodes': [], 'links': []}
            
        universe_map[u_id]['nodes'].append({
            'id': row['id'],
            'label': row['label'],
            'content': row['content'],
            'x': row['x'],
            'y': row['y'],
            'z': row['z'],
            'isExpanded': bool(row['is_expanded']),
            'agentType': row['agent_type'],
            'imageUrl': row['image_url'],
            'inheritedFromId': row['inherited_from_id'],
            'inheritedIndex': row['inherited_index'],
            'hasManualTitle': bool(row['has_manual_title']),
            'isPublic': bool(row['is_public']),
            'systemModule': row['system_module'],
            'manualWidth': row['manual_width'],
            'manualHeight': row['manual_height'],
            'isPinned': bool(row['is_pinned']),
            'pinnedX': row['pinned_x'],
            'pinnedY': row['pinned_y']
        })
        
    for row in conn.execute('SELECT * FROM edges'):
        u_id = row['universe_id']
        if u_id not in universe_map:
            universe_map[u_id] = {'nodes': [], 'links': []}
            
        universe_map[u_id]['links'].append({
            'source': row['source'],
            'target': row['target'],
            'weight': row['weight']
        })
        
    conn.close()
    return universe_map

def get_public_gossip():
    conn = get_db()
    gossips = []
    
    # Get user's own public nodes just for reference
    for row in conn.execute('SELECT * FROM nodes WHERE is_public = 1 LIMIT 10'):
        gossips.append({
            'id': row['id'],
            'label': row['label'],
            'content': row['content'],
            'source_peer': 'Prime Node',
            'thought_topic': row['label']
        })
    conn.close()
    
    # Now pull the REAL subagent gossip from the LGNN core (lgnn.db)
    try:
        from aethelnet_node.database import get_db_connection as get_lgnn_db
        lgnn_conn = get_lgnn_db()
        # Find all nodes injected by peers (source_tag starts with p2p_)
        for row in lgnn_conn.execute("SELECT id, text_content, source_tag FROM lgnn_nodes WHERE source_tag LIKE 'p2p_%' AND source_tag NOT LIKE '%expertise%' ORDER BY last_updated DESC LIMIT 20"):
            peer_name = row['source_tag'].replace('p2p_', '')
            gossips.append({
                'id': row['id'],
                'source_peer': peer_name,
                'thought_topic': row['text_content']
            })
        lgnn_conn.close()
    except Exception as e:
        print(f"Error fetching real gossip: {e}")
        
    return gossips

def save_graph(universe_map):
    conn = get_db()
    c = conn.cursor()
    
    # Delete all data for full sync
    c.execute('DELETE FROM nodes')
    c.execute('DELETE FROM edges')
    
    flat_nodes = []
    flat_edges = []
    
    for u_id, data in universe_map.items():
        for n in data.get('nodes', []):
            flat_nodes.append((
                n.get('id'), u_id, n.get('label'), n.get('content'), n.get('x'), n.get('y'), n.get('z', 0),
                1 if n.get('isExpanded') else 0, n.get('agentType'), n.get('imageUrl'),
                n.get('inheritedFromId'), n.get('inheritedIndex'),
                1 if n.get('hasManualTitle') else 0,
                1 if ('#public' in (str(n.get('content', '')) + str(n.get('label', ''))).lower()) else 0,
                n.get('systemModule'), n.get('manualWidth'), n.get('manualHeight'),
                1 if n.get('isPinned') else 0, n.get('pinnedX'), n.get('pinnedY')
            ))
        for e in data.get('links', []):
            src = e.get('source')
            tgt = e.get('target')
            src_id = src.get('id') if isinstance(src, dict) else src
            tgt_id = tgt.get('id') if isinstance(tgt, dict) else tgt
            
            flat_edges.append((
                u_id, src_id, tgt_id, e.get('weight', 1.0)
            ))
            
    # Insert nodes
    c.executemany('''
        INSERT INTO nodes (id, universe_id, label, content, x, y, z, is_expanded, agent_type, image_url, inherited_from_id, inherited_index, has_manual_title, is_public, system_module, manual_width, manual_height, is_pinned, pinned_x, pinned_y)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', flat_nodes)
    
    # Insert edges
    c.executemany('''
        INSERT INTO edges (universe_id, source, target, weight) VALUES (?, ?, ?, ?)
    ''', flat_edges)
    
    conn.commit()
    conn.close()

# Initialize on import
init_db()
