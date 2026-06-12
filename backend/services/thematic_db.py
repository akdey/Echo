import sqlite3
import os
import time
import logging
import asyncio
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

# Resolve persistent storage directory
PERSISTENT_STORAGE_DIR = os.environ.get("PERSISTENT_STORAGE_DIR")
if not PERSISTENT_STORAGE_DIR:
    services_dir = os.path.dirname(os.path.abspath(__file__))
    backend_dir = os.path.dirname(services_dir)
    PERSISTENT_STORAGE_DIR = os.path.join(backend_dir, "data_store")
else:
    PERSISTENT_STORAGE_DIR = os.path.abspath(PERSISTENT_STORAGE_DIR)

DB_PATH = os.path.join(PERSISTENT_STORAGE_DIR, "thematic_knowledge_graph.db")

def _get_connection():
    os.makedirs(PERSISTENT_STORAGE_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes tables and seeds default data if tables are empty."""
    logger.info("Initializing SQLite thematic database at %s", DB_PATH)
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        
        # Create Nodes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                label TEXT NOT NULL,
                description TEXT
            );
        """)
        
        # Create Edges table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                role TEXT,
                pricing_power TEXT,
                catalyst_relevance TEXT,
                timestamp INTEGER NOT NULL,
                FOREIGN KEY(source_id) REFERENCES nodes(id) ON DELETE CASCADE,
                FOREIGN KEY(target_id) REFERENCES nodes(id) ON DELETE CASCADE,
                UNIQUE(source_id, target_id, relation_type)
            );
        """)
        
        # Create Indices
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_timestamp ON edges(timestamp);")
        
        conn.commit()
        
        # Check if empty, then seed default data
        cursor.execute("SELECT COUNT(*) as cnt FROM nodes;")
        row = cursor.fetchone()
        if row["cnt"] == 0:
            logger.info("Thematic database is empty. Seeding default knowledge graph...")
            _seed_default_graph(cursor)
            conn.commit()
            
    except Exception as e:
        logger.error("Failed to initialize thematic database: %s", str(e), exc_info=True)
        conn.rollback()
    finally:
        conn.close()

def _seed_default_graph(cursor):
    default_themes = {
        "DEFENSE": ("THEME", "Defense Sector", "Defense acquisition, military upgrades, and indigenization"),
        "RAILWAYS": ("THEME", "Railways Sector", "Railway modernization, high-speed rail, wagon procurement, and metro lines"),
        "RENEWABLE_ENERGY": ("THEME", "Renewable Energy Sector", "Solar power expansion, wind energy projects, grid transmission, green hydrogen"),
        "SEMICONDUCTORS": ("THEME", "Semiconductors Sector", "Semiconductor manufacturing, silicon wafers, testing, and packaging (OSAT)")
    }
    
    default_suppliers = {
        "DEFENSE": [
            {"symbol": "SOLARINDS.NS", "name": "Solar Industries India", "role": "Propellants and High-Energy Explosives supplier for missiles/rockets", "pricing_power": "High (Monopoly/Duopoly)", "relevance": "Procurement of missiles, ammunition, and explosives"},
            {"symbol": "PREMEXPLOS.NS", "name": "Premier Explosives", "role": "Solid Propellants and missile explosive material supplier", "pricing_power": "High (Specialized monopoly)", "relevance": "Solid rocket motors, propellants"},
            {"symbol": "MIDHANI.NS", "name": "Mishra Dhatu Nigam", "role": "Specialty steel, titanium alloys, and superalloys", "pricing_power": "High (Strategic PSU monopoly)", "relevance": "Armor plates, missile casings, fighter jets, submarines"},
            {"symbol": "BEL.NS", "name": "Bharat Electronics", "role": "Military radar, sonar, and avionics communication systems", "pricing_power": "High (Defense electronics giant)", "relevance": "Electronics, systems integration, avionics"},
            {"symbol": "HAL.NS", "name": "Hindustan Aeronautics", "role": "Fighter jets, helicopters, gas turbines, and structural aerospace components", "pricing_power": "High (National aerospace monopoly)", "relevance": "Combat aircraft, helicopters, aerospace indigenization"},
            {"symbol": "MAZDOCK.NS", "name": "Mazagon Dock Shipbuilders", "role": "Submarines, destroyers, and naval warships", "pricing_power": "High (Naval PSU monopoly)", "relevance": "Warships, submarines, naval defense acquisition"},
            {"symbol": "BEML.NS", "name": "BEML Limited", "role": "Heavy military trucks, missile launchers, and bulldozers", "pricing_power": "High (Specialized defense PSU supplier)", "relevance": "Missile launchers, military transports, heavy ground systems"}
        ],
        "RAILWAYS": [
            {"symbol": "TITAGARH.NS", "name": "Titagarh Rail Systems", "role": "Railway wagons, passenger coaches, and metro trainsets", "pricing_power": "High (Wagon major)", "relevance": "Freight wagons, passenger coaches, high-speed bogies"},
            {"symbol": "TEXRAIL.NS", "name": "Texmaco Rail & Engineering", "role": "Railway wagons, steel castings, and track EPC", "pricing_power": "Medium", "relevance": "Freight wagons, track electrification, signals"},
            {"symbol": "RAMKRISHN.NS", "name": "Ramkrishna Forgings", "role": "Railway wheelsets, axles, and heavy forged components", "pricing_power": "High (Global forging exporter)", "relevance": "Wheel and axle assemblies, structural forgings"},
            {"symbol": "RVNL.NS", "name": "Rail Vikas Nagar", "role": "Railway infrastructure project execution and line doubling", "pricing_power": "Medium (EPC execution)", "relevance": "Infrastructure, track laying, new lines"},
            {"symbol": "IRCON.NS", "name": "IRCON International", "role": "Specialized railway tunnels, bridges, and international rail EPC", "pricing_power": "Medium (PSU builder)", "relevance": "Bridges, tunnels, railway electrification"}
        ],
        "RENEWABLE_ENERGY": [
            {"symbol": "BORORENEW.NS", "name": "Borosil Renewables", "role": "Solar tempered glass manufacturing", "pricing_power": "High (Sole domestic solar glass manufacturer)", "relevance": "Solar glass modules, photovoltaic cell covers"},
            {"symbol": "SUZLON.NS", "name": "Suzlon Energy", "role": "Wind turbine generators and wind farm construction", "pricing_power": "High (Wind turbine major)", "relevance": "Wind turbines, wind farm capacity additions"},
            {"symbol": "KPIGREEN.NS", "name": "KPI Green Energy", "role": "Solar power developer and IPP (Independent Power Producer)", "pricing_power": "Medium", "relevance": "Solar power capacity, captive solar parks"},
            {"symbol": "GEPIL.NS", "name": "GE Power India", "role": "Thermal and renewable grid transmission, boilers, and transformers", "pricing_power": "High (Utility engineering)", "relevance": "Power transmission, grid substation transformers"}
        ],
        "SEMICONDUCTORS": [
            {"symbol": "CGPOWER.NS", "name": "CG Power and Industrial Solutions", "role": "Joint-venture OSAT assembly and testing plant", "pricing_power": "High (Early mover OSAT)", "relevance": "OSAT, chip packaging and testing facilities"},
            {"symbol": "KAYNES.NS", "name": "Kaynes Technology", "role": "Electronic Manufacturing Services (EMS) and semiconductor OSAT packaging", "pricing_power": "High (EMS leader)", "relevance": "OSAT facility setup, electronic board sub-assembly"},
            {"symbol": "LINDEINDIA.NS", "name": "Linde India", "role": "Specialty ultra-pure gases (argon, helium, nitrogen) for cleanrooms", "pricing_power": "High (Industrial gases monopoly)", "relevance": "Silicon wafer cleaning, semiconductor process gases"}
        ]
    }
    
    # Insert theme nodes
    for theme_id, (ntype, name, desc) in default_themes.items():
        cursor.execute(
            "INSERT OR IGNORE INTO nodes (id, type, label, description) VALUES (?, ?, ?, ?);",
            (theme_id, ntype, name, desc)
        )
        
    now = int(time.time())
    
    # Insert suppliers and edges
    for theme_id, suppliers in default_suppliers.items():
        for s in suppliers:
            # Insert supplier node
            cursor.execute(
                "INSERT OR IGNORE INTO nodes (id, type, label, description) VALUES (?, ?, ?, ?);",
                (s["symbol"], "COMPANY", s["name"], s["role"])
            )
            # Insert edge
            cursor.execute(
                """
                INSERT OR IGNORE INTO edges 
                (source_id, target_id, relation_type, weight, role, pricing_power, catalyst_relevance, timestamp) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (s["symbol"], theme_id, "SUPPLIES_SECTOR", 1.0, s["role"], s["pricing_power"], s["relevance"], now)
            )

# Async wrappers around SQLite functions to avoid blocking the event loop
async def run_in_pool(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

# Synchronous CRUD implementations to be run in executor
def _add_node(id: str, type: str, label: str, description: Optional[str] = None):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO nodes (id, type, label, description) VALUES (?, ?, ?, ?);",
            (id.upper(), type.upper(), label, description)
        )
        conn.commit()
        logger.info("Successfully added node: %s", id)
        return True
    except Exception as e:
        logger.error("Failed to add node %s: %s", id, e)
        return False
    finally:
        conn.close()

def _delete_node(id: str):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM nodes WHERE id = ?;", (id.upper(),))
        conn.commit()
        logger.info("Successfully deleted node: %s (and cascading edges)", id)
        return True
    except Exception as e:
        logger.error("Failed to delete node %s: %s", id, e)
        return False
    finally:
        conn.close()

def _add_edge(
    source_id: str, 
    target_id: str, 
    relation_type: str, 
    weight: float = 1.0, 
    role: Optional[str] = None, 
    pricing_power: Optional[str] = None, 
    catalyst_relevance: Optional[str] = None,
    timestamp: Optional[int] = None
):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        t = timestamp if timestamp is not None else int(time.time())
        cursor.execute(
            """
            INSERT OR REPLACE INTO edges 
            (source_id, target_id, relation_type, weight, role, pricing_power, catalyst_relevance, timestamp) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (source_id.upper(), target_id.upper(), relation_type.upper(), weight, role, pricing_power, catalyst_relevance, t)
        )
        conn.commit()
        logger.info("Successfully added edge: %s -> %s (%s)", source_id, target_id, relation_type)
        return True
    except Exception as e:
        logger.error("Failed to add edge %s -> %s: %s", source_id, target_id, e)
        return False
    finally:
        conn.close()

def _delete_edge(edge_id: int):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM edges WHERE id = ?;", (edge_id,))
        conn.commit()
        logger.info("Successfully deleted edge: %d", edge_id)
        return True
    except Exception as e:
        logger.error("Failed to delete edge %d: %s", edge_id, e)
        return False
    finally:
        conn.close()

def _delete_edge_by_nodes(source_id: str, target_id: str, relation_type: str):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM edges WHERE source_id = ? AND target_id = ? AND relation_type = ?;",
            (source_id.upper(), target_id.upper(), relation_type.upper())
        )
        conn.commit()
        logger.info("Deleted edge: %s -> %s (%s)", source_id, target_id, relation_type)
        return True
    except Exception as e:
        logger.error("Failed to delete edge %s -> %s: %s", source_id, target_id, e)
        return False
    finally:
        conn.close()

def _get_graph_data() -> Dict[str, Any]:
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, type, label, description FROM nodes;")
        nodes = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("SELECT id, source_id, target_id, relation_type, weight, role, pricing_power, catalyst_relevance, timestamp FROM edges;")
        edges = [dict(row) for row in cursor.fetchall()]
        
        return {"nodes": nodes, "edges": edges}
    except Exception as e:
        logger.error("Failed to fetch graph data: %s", e)
        return {"nodes": [], "edges": []}
    finally:
        conn.close()

def _get_suppliers_for_theme(theme_name: str) -> List[Dict[str, Any]]:
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        # Find theme node id
        cursor.execute("SELECT id FROM nodes WHERE id = ? OR label LIKE ?;", (theme_name.upper(), f"%{theme_name}%"))
        theme_row = cursor.fetchone()
        if not theme_row:
            return []
        
        theme_id = theme_row["id"]
        cursor.execute(
            """
            SELECT n.id as symbol, n.label as name, n.description as node_desc,
                   e.id as edge_id, e.relation_type, e.weight, e.role, e.pricing_power, e.catalyst_relevance, e.timestamp
            FROM edges e
            JOIN nodes n ON e.source_id = n.id
            WHERE e.target_id = ?;
            """,
            (theme_id,)
        )
        return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error("Failed to fetch suppliers for theme %s: %s", theme_name, e)
        return []
    finally:
        conn.close()

def _prune_expired_catalysts(ttl_days: int = 180):
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cutoff_time = int(time.time()) - (ttl_days * 86400)
        cursor.execute(
            "DELETE FROM edges WHERE relation_type = 'CONTRACT_WIN' AND timestamp < ?;",
            (cutoff_time,)
        )
        deleted_count = cursor.rowcount
        conn.commit()
        if deleted_count > 0:
            logger.info("Pruned %d expired contract wins older than %d days.", deleted_count, ttl_days)
        return deleted_count
    except Exception as e:
        logger.error("Failed to prune expired catalysts: %s", e)
        return 0
    finally:
        conn.close()

# Public Async API
async def add_node_async(id: str, type: str, label: str, description: Optional[str] = None) -> bool:
    return await run_in_pool(_add_node, id, type, label, description)

async def delete_node_async(id: str) -> bool:
    return await run_in_pool(_delete_node, id)

async def add_edge_async(
    source_id: str, 
    target_id: str, 
    relation_type: str, 
    weight: float = 1.0, 
    role: Optional[str] = None, 
    pricing_power: Optional[str] = None, 
    catalyst_relevance: Optional[str] = None,
    timestamp: Optional[int] = None
) -> bool:
    return await run_in_pool(_add_edge, source_id, target_id, relation_type, weight, role, pricing_power, catalyst_relevance, timestamp)

async def delete_edge_async(edge_id: int) -> bool:
    return await run_in_pool(_delete_edge, edge_id)

async def delete_edge_by_nodes_async(source_id: str, target_id: str, relation_type: str) -> bool:
    return await run_in_pool(_delete_edge_by_nodes, source_id, target_id, relation_type)

async def get_graph_data_async() -> Dict[str, Any]:
    return await run_in_pool(_get_graph_data)

async def get_suppliers_for_theme_async(theme_name: str) -> List[Dict[str, Any]]:
    return await run_in_pool(_get_suppliers_for_theme, theme_name)

async def prune_expired_catalysts_async(ttl_days: int = 180) -> int:
    return await run_in_pool(_prune_expired_catalysts, ttl_days)
