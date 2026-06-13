# Deprecated: This module has been renamed to db_handler.py.
# Please import from backend.services.db_handler instead.

from backend.services.db_handler import (
    query_db as query_supabase,
    upsert_db as upsert_supabase,
    delete_db as delete_supabase,
    rpc_db as rpc_supabase,
    verify_db_connection as verify_supabase_connection,
    IS_DB_CONFIGURED as IS_SUPABASE_CONFIGURED,
    IS_DB_CONFIGURED
)
