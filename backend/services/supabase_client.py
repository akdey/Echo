import os
import logging
import requests
import asyncio
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()

# Check if credentials are present
IS_SUPABASE_CONFIGURED = bool(SUPABASE_URL and SUPABASE_KEY)

if not IS_SUPABASE_CONFIGURED:
    logger.warning("Supabase environment variables (SUPABASE_URL, SUPABASE_KEY) are missing. App will degrade to local storage fallbacks.")

def _get_headers() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def _query_sync(table: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if not IS_SUPABASE_CONFIGURED:
        return []
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        r = requests.get(url, headers=_get_headers(), params=params, timeout=10)
        if r.status_code in [200, 201]:
            return r.json()
        logger.error("Supabase GET error on %s: [%d] %s", table, r.status_code, r.text)
        return []
    except Exception as e:
        logger.error("Supabase GET connection failed on %s: %s", table, str(e))
        return []

def _upsert_sync(table: str, payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not IS_SUPABASE_CONFIGURED:
        return []
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    headers = _get_headers()
    # PostgREST uses resolution=merge for upsert behavior when keys are specified
    headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        if r.status_code in [200, 201]:
            return r.json()
        logger.error("Supabase UPSERT error on %s: [%d] %s", table, r.status_code, r.text)
        return []
    except Exception as e:
        logger.error("Supabase UPSERT connection failed on %s: %s", table, str(e))
        return []

def _delete_sync(table: str, query_params: Dict[str, str]) -> List[Dict[str, Any]]:
    if not IS_SUPABASE_CONFIGURED:
        return []
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        r = requests.delete(url, headers=_get_headers(), params=query_params, timeout=10)
        if r.status_code in [200, 204]:
            return r.json() if r.text else []
        logger.error("Supabase DELETE error on %s: [%d] %s", table, r.status_code, r.text)
        return []
    except Exception as e:
        logger.error("Supabase DELETE connection failed on %s: %s", table, str(e))
        return []

def _rpc_sync(function_name: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not IS_SUPABASE_CONFIGURED:
        return []
    url = f"{SUPABASE_URL}/rest/v1/rpc/{function_name}"
    try:
        r = requests.post(url, headers=_get_headers(), json=payload, timeout=10)
        if r.status_code in [200, 201]:
            return r.json()
        logger.error("Supabase RPC error on %s: [%d] %s", function_name, r.status_code, r.text)
        return []
    except Exception as e:
        logger.error("Supabase RPC connection failed on %s: %s", function_name, str(e))
        return []

# Public Async API using thread pool executor
async def query_supabase(table: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _query_sync, table, params)

async def upsert_supabase(table: str, payload: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _upsert_sync, table, payload)

async def delete_supabase(table: str, query_params: Dict[str, str]) -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _delete_sync, table, query_params)

async def rpc_supabase(function_name: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _rpc_sync, function_name, payload)

async def verify_supabase_connection() -> bool:
    """Verifies that the Supabase endpoint is configured and reachable."""
    if not IS_SUPABASE_CONFIGURED:
        return False
    try:
        # Check by running a simple select limit 1 on companies (or nodes if they exist)
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(
            None,
            lambda: requests.get(f"{SUPABASE_URL}/rest/v1/companies", headers=_get_headers(), params={"limit": 1}, timeout=5)
        )
        return res.status_code in [200, 201]
    except Exception:
        return False
