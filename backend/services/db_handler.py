import os
import logging
import asyncio
import datetime
import uuid
import json
from typing import Dict, Any, List, Optional
from sqlalchemy import create_engine, text, inspect, Column, String, Integer, Float, Boolean, DateTime, Text, JSON
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

# Retrieve and normalize DATABASE_URL
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    # Fall back to local SQLite database in the persistent data store directory
    PERSISTENT_STORAGE_DIR = os.environ.get("PERSISTENT_STORAGE_DIR")
    if not PERSISTENT_STORAGE_DIR:
        services_dir = os.path.dirname(os.path.abspath(__file__))
        backend_dir = os.path.dirname(services_dir)
        PERSISTENT_STORAGE_DIR = os.path.join(backend_dir, "data_store")
    else:
        PERSISTENT_STORAGE_DIR = os.path.abspath(PERSISTENT_STORAGE_DIR)
        
    os.makedirs(PERSISTENT_STORAGE_DIR, exist_ok=True)
    db_path = os.path.join(PERSISTENT_STORAGE_DIR, "echo_database.db")
    DATABASE_URL = f"sqlite:///{db_path}"
    logger.info("No DATABASE_URL found. Initializing local SQLite database at: %s", db_path)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Configure dialect-specific arguments
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# Create SQLAlchemy Engine
try:
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool if not DATABASE_URL.startswith("sqlite") else None,
        connect_args=connect_args,
        pool_pre_ping=True
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    logger.info("SQLAlchemy database engine initialized successfully.")
except Exception as e:
    logger.error("Failed to initialize SQLAlchemy engine: %s", e, exc_info=True)
    raise e

Base = declarative_base()

# --- SQLAlchemy Models ---
class Company(Base):
    __tablename__ = "companies"
    symbol = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    sector = Column(String)
    industry = Column(String)
    market_cap_cr = Column(Float)
    description = Column(Text)
    
    def to_dict(self):
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector": self.sector,
            "industry": self.industry,
            "market_cap_cr": self.market_cap_cr,
            "description": self.description
        }

class DailyBhavcopy(Base):
    __tablename__ = "daily_bhavcopy"
    symbol = Column(String, primary_key=True)
    trade_date = Column(String, primary_key=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    amount = Column(Float)
    delivery_qty = Column(Float)
    delivery_pct = Column(Float)
    
    def to_dict(self):
        return {
            "symbol": self.symbol,
            "trade_date": self.trade_date,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "delivery_qty": self.delivery_qty,
            "delivery_pct": self.delivery_pct
        }

class SectorMomentum(Base):
    __tablename__ = "sector_momentum"
    sector_name = Column(String, primary_key=True)
    index_symbol = Column(String)
    current_price = Column(Float, nullable=False)
    sma_50 = Column(Float)
    sma_150 = Column(Float)
    rs_score = Column(Float, nullable=False)
    rs_change_4w = Column(Float)
    momentum_regime = Column(String, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    def to_dict(self):
        return {
            "sector_name": self.sector_name,
            "index_symbol": self.index_symbol,
            "current_price": self.current_price,
            "sma_50": self.sma_50,
            "sma_150": self.sma_150,
            "rs_score": self.rs_score,
            "rs_change_4w": self.rs_change_4w,
            "momentum_regime": self.momentum_regime,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class TradeJournal(Base):
    __tablename__ = "trade_journal"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol = Column(String, nullable=False)
    entry_date = Column(String, nullable=False)
    entry_price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    conviction_score = Column(Integer, nullable=False)
    catalyst = Column(Text)
    stop_loss = Column(Float, nullable=False)
    target_price = Column(Float)
    exit_date = Column(String)
    exit_price = Column(Float)
    pnl = Column(Float)
    outcome_notes = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "entry_date": self.entry_date,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "conviction_score": self.conviction_score,
            "catalyst": self.catalyst,
            "stop_loss": self.stop_loss,
            "target_price": self.target_price,
            "exit_date": self.exit_date,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
            "outcome_notes": self.outcome_notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class ConvictionMatrix(Base):
    __tablename__ = "conviction_matrix"
    symbol = Column(String, primary_key=True)
    conviction_score = Column(Integer, nullable=False)
    technical_score = Column(Integer, nullable=False, default=0)
    smart_money_score = Column(Integer, nullable=False, default=0)
    thematic_score = Column(Integer, nullable=False, default=0)
    fundamental_score = Column(Integer, nullable=False, default=0)
    trap_penalty = Column(Integer, nullable=False, default=0)
    verdict = Column(Text, nullable=False)
    stop_loss_level = Column(Float)
    catalyst_tags = Column(JSON, default=list)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    def to_dict(self):
        return {
            "symbol": self.symbol,
            "conviction_score": self.conviction_score,
            "technical_score": self.technical_score,
            "smart_money_score": self.smart_money_score,
            "thematic_score": self.thematic_score,
            "fundamental_score": self.fundamental_score,
            "trap_penalty": self.trap_penalty,
            "verdict": self.verdict,
            "stop_loss_level": self.stop_loss_level,
            "catalyst_tags": self.catalyst_tags if isinstance(self.catalyst_tags, list) else [],
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class Surveillance(Base):
    __tablename__ = "surveillance"
    symbol = Column(String, primary_key=True)
    stage = Column(String)
    category = Column(String)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    def to_dict(self):
        return {
            "symbol": self.symbol,
            "stage": self.stage,
            "category": self.category,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }

class InsiderDisclosure(Base):
    __tablename__ = "insider_disclosures"
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False)
    acquirer_name = Column(String, nullable=False)
    category_of_person = Column(String)
    transaction_type = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    value_rs = Column(Float)
    mode_of_acquisition = Column(String)
    trade_date = Column(String, nullable=False)
    disclosure_date = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "acquirer_name": self.acquirer_name,
            "category_of_person": self.category_of_person,
            "transaction_type": self.transaction_type,
            "quantity": self.quantity,
            "value_rs": self.value_rs,
            "mode_of_acquisition": self.mode_of_acquisition,
            "trade_date": self.trade_date,
            "disclosure_date": self.disclosure_date,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

class NewsSignal(Base):
    __tablename__ = "news_signals"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tier = Column(Integer, nullable=False)
    query = Column(Text)
    source_title = Column(Text)
    source_url = Column(Text)
    theme = Column(String)
    affected_sectors = Column(JSON, default=list)
    symbol = Column(String)
    is_material_catalyst = Column(Boolean)
    event_type = Column(String)
    sentiment = Column(String)
    conviction_adjustment = Column(Integer, default=0)
    raw_snippet = Column(Text)
    llm_summary = Column(Text)
    metadata = Column(JSON, default=dict)
    processed_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "tier": self.tier,
            "query": self.query,
            "source_title": self.source_title,
            "source_url": self.source_url,
            "theme": self.theme,
            "affected_sectors": self.affected_sectors if isinstance(self.affected_sectors, list) else [],
            "symbol": self.symbol,
            "is_material_catalyst": self.is_material_catalyst,
            "event_type": self.event_type,
            "sentiment": self.sentiment,
            "conviction_adjustment": self.conviction_adjustment,
            "raw_snippet": self.raw_snippet,
            "llm_summary": self.llm_summary,
            "metadata": self.metadata if isinstance(self.metadata, dict) else {},
            "processed_at": self.processed_at.isoformat() if self.processed_at else None
        }

class ConvictionOverride(Base):
    __tablename__ = "conviction_overrides"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    symbol = Column(String, nullable=False)
    override_points = Column(Integer, nullable=False)
    reason = Column(Text)
    source = Column(String)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "override_points": self.override_points,
            "reason": self.reason,
            "source": self.source,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }

# TABLE_MODEL_MAP resolves API string names to SQLAlchemy Class structures
TABLE_MODEL_MAP = {
    "companies": Company,
    "daily_bhavcopy": DailyBhavcopy,
    "sector_momentum": SectorMomentum,
    "trade_journal": TradeJournal,
    "conviction_matrix": ConvictionMatrix,
    "surveillance": Surveillance,
    "insider_disclosures": InsiderDisclosure,
    "news_signals": NewsSignal,
    "conviction_overrides": ConvictionOverride
}

IS_DB_CONFIGURED = True  # Always configured since we default to SQLite if no URL is set

# --- Sync Database Engine Methods ---
def _query_sync(table: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    model = TABLE_MODEL_MAP.get(table)
    if not model:
        logger.error("No model definition mapped for table: %s", table)
        return []
        
    with SessionLocal() as session:
        query = session.query(model)
        if params:
            for k, v in params.items():
                if k in ["select", "order", "limit"]:
                    continue
                # Map column attribute
                if not hasattr(model, k):
                    continue
                attr = getattr(model, k)
                if isinstance(v, str):
                    if v.startswith("eq."):
                        query = query.filter(attr == v[3:])
                    elif v.startswith("gt."):
                        query = query.filter(attr > v[3:])
                    elif v.startswith("gte."):
                        query = query.filter(attr >= v[4:])
                    elif v.startswith("lt."):
                        query = query.filter(attr < v[3:])
                    elif v.startswith("lte."):
                        query = query.filter(attr <= v[4:])
                    elif v.startswith("like."):
                        query = query.filter(attr.like(v[5:]))
                    elif v.startswith("ilike."):
                        query = query.filter(attr.ilike(v[6:]))
                    elif v.startswith("in."):
                        vals = [x.strip() for x in v[3:].strip("()").split(",")]
                        query = query.filter(attr.in_(vals))
                    else:
                        query = query.filter(attr == v)
                else:
                    query = query.filter(attr == v)
                    
            if "order" in params:
                order_val = params["order"]
                if "." in order_val:
                    col, direction = order_val.split(".", 1)
                    if hasattr(model, col):
                        attr = getattr(model, col)
                        if direction.lower() == "desc":
                            query = query.order_by(attr.desc())
                        else:
                            query = query.order_by(attr.asc())
                else:
                    if hasattr(model, order_val):
                        query = query.order_by(getattr(model, order_val))
                        
            if "limit" in params:
                try:
                    query = query.limit(int(params["limit"]))
                except ValueError:
                    pass
                    
        return [row.to_dict() for row in query.all()]

def _upsert_sync(table: str, payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    model = TABLE_MODEL_MAP.get(table)
    if not model:
        logger.error("No model definition mapped for table: %s", table)
        return []
    if not payload:
        return []
        
    results = []
    with SessionLocal() as session:
        try:
            for item in payload:
                existing = None
                
                # Check target table primary key / unique target values
                if table == "daily_bhavcopy":
                    existing = session.query(model).filter_by(
                        symbol=item.get("symbol"),
                        trade_date=item.get("trade_date")
                    ).first()
                elif table == "insider_disclosures":
                    existing = session.query(model).filter_by(
                        symbol=item.get("symbol"),
                        acquirer_name=item.get("acquirer_name"),
                        trade_date=item.get("trade_date"),
                        quantity=item.get("quantity"),
                        transaction_type=item.get("transaction_type")
                    ).first()
                else:
                    # Generic inspect lookup for single primary key
                    pk_names = [key.name for key in inspect(model).primary_key]
                    filter_dict = {pk: item.get(pk) for pk in pk_names if item.get(pk) is not None}
                    if filter_dict:
                        existing = session.query(model).filter_by(**filter_dict).first()
                        
                if existing:
                    # Update fields dynamically
                    for k, v in item.items():
                        setattr(existing, k, v)
                    db_obj = existing
                else:
                    # Populate default primary key string if uuid column is absent in input
                    if hasattr(model, "id") and item.get("id") is None:
                        item["id"] = str(uuid.uuid4())
                    db_obj = model(**item)
                    session.add(db_obj)
                    
                session.flush()
                results.append(db_obj.to_dict())
            session.commit()
            return results
        except Exception as e:
            session.rollback()
            logger.error("ORM Database upsert error on %s: %s", table, e)
            return []

def _delete_sync(table: str, query_params: Dict[str, str]) -> List[Dict[str, Any]]:
    model = TABLE_MODEL_MAP.get(table)
    if not model:
        logger.error("No model definition mapped for table: %s", table)
        return []
        
    results = []
    with SessionLocal() as session:
        try:
            query = session.query(model)
            for k, v in query_params.items():
                if not hasattr(model, k):
                    continue
                attr = getattr(model, k)
                if isinstance(v, str):
                    if v.startswith("eq."):
                        query = query.filter(attr == v[3:])
                    elif v.startswith("gt."):
                        query = query.filter(attr > v[3:])
                    elif v.startswith("lt."):
                        query = query.filter(attr < v[3:])
                    else:
                        query = query.filter(attr == v)
                else:
                    query = query.filter(attr == v)
                    
            objs = query.all()
            for obj in objs:
                results.append(obj.to_dict())
                session.delete(obj)
            session.commit()
            return results
        except Exception as e:
            session.rollback()
            logger.error("ORM Database delete error on %s: %s", table, e)
            return []

def _rpc_sync(function_name: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Stored procedures require Postgres. We compile direct text query via session.execute
    with SessionLocal() as session:
        try:
            if not payload:
                sql = text(f"SELECT * FROM {function_name}();")
                res = session.execute(sql)
            else:
                keys = list(payload.keys())
                params_str = ", ".join([f"{k} => :{k}" for k in keys])
                sql = text(f"SELECT * FROM {function_name}({params_str});")
                res = session.execute(sql, payload)
                
            return [dict(row._mapping) for row in res.all()]
        except Exception as e:
            logger.error("ORM Stored Procedure (RPC) execute failed on %s: %s", function_name, e)
            return []

def _verify_db_connection() -> bool:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1;"))
        return True
    except Exception as e:
        logger.error("ORM Database connection check failed: %s", e)
        return False

# --- Public Async APIs ---
async def query_db(table: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _query_sync, table, params)

async def upsert_db(table: str, payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _upsert_sync, table, payload)

async def delete_db(table: str, query_params: Dict[str, str]) -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _delete_sync, table, query_params)

async def rpc_db(function_name: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _rpc_sync, function_name, payload)

async def verify_db_connection() -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _verify_db_connection)

def init_db():
    """Create all tables defined in SQLAlchemy metadata if they don't exist."""
    logger.info("Initializing generic ORM database tables (create_all)...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database schemas verified successfully.")
    except Exception as e:
        logger.error("Failed to execute database schema create_all: %s", e, exc_info=True)

# --- Backward Compatibility Aliases ---
query_supabase = query_db
upsert_supabase = upsert_db
delete_supabase = delete_db
rpc_supabase = rpc_db
verify_supabase_connection = verify_db_connection
IS_SUPABASE_CONFIGURED = IS_DB_CONFIGURED
