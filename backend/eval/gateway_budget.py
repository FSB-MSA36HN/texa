"""Backward-compatible evaluation import for the shared Texa runtime budget guard."""
try:  # package import (tests and ``python -m``)
    from texa.gateway_budget import (GatewayBudgetGuard, GatewayBudgetRequestError,
                                     configure_gateway_from_environment, update_ledger,
                                     validate_credentials_path)
except ImportError:  # direct script import when backend/eval is on sys.path
    from texa.gateway_budget import (GatewayBudgetGuard, GatewayBudgetRequestError,
                                     configure_gateway_from_environment, update_ledger,
                                     validate_credentials_path)

__all__ = ["GatewayBudgetGuard", "GatewayBudgetRequestError", "configure_gateway_from_environment",
           "update_ledger", "validate_credentials_path"]
