"""
Info tools for Tekla model operations.
"""

from typing import Any

from tekla_mcp_server.tekla.model import TeklaModel
from tekla_mcp_server.utils import log_function_call


@log_function_call
def tool_check_tekla_connection() -> dict[str, Any]:
    """
    Check Tekla connection status.

    Returns:
        Connection status with fields:
          - connected: boolean
          - model_path: str | null
          - message: str
    """
    try:
        tekla_model = TeklaModel()
        return {
            "connected": True,
            "model_path": tekla_model.model.GetInfo().ModelPath,
            "message": "Connected to Tekla",
        }
    except ConnectionError as e:
        return {"connected": False, "model_path": None, "message": str(e)}
    except Exception as e:
        return {"connected": False, "model_path": None, "message": f"Error: {e}"}
