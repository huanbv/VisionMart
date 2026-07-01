"""Payment gateway abstraction.

The `checkout()` flow calls a `PaymentGateway.charge()` before creating the
paid Order. Multiple concrete implementations can be swapped via the
`PAYMENT_GATEWAY` env var:
  * `simulated` — always successful (default, used for demos and MVP).
  * `vnpay` / `momo` — placeholders for future real integrations.
"""

from __future__ import annotations

import random
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from app.config.settings import Settings, get_settings


@dataclass(frozen=True)
class PaymentResult:
    success: bool
    reference: str
    status: str
    gateway: str
    error: str | None = None


class PaymentGateway(ABC):
    name: str = "abstract"

    @abstractmethod
    async def charge(
        self,
        *,
        cart_id: uuid.UUID,
        amount: Decimal,
        currency: str,
        customer_id: uuid.UUID | None,
    ) -> PaymentResult: ...


class SimulatedPaymentGateway(PaymentGateway):
    name = "simulated"

    def __init__(self, success_rate: float = 1.0) -> None:
        self._success_rate = max(0.0, min(1.0, success_rate))

    async def charge(
        self,
        *,
        cart_id: uuid.UUID,
        amount: Decimal,
        currency: str,
        customer_id: uuid.UUID | None,
    ) -> PaymentResult:
        ok = random.random() < self._success_rate
        return PaymentResult(
            success=ok,
            reference=f"SIM-{uuid.uuid4().hex[:16].upper()}",
            status="captured" if ok else "declined",
            gateway=self.name,
            error=None if ok else "simulated_decline",
        )


def build_payment_gateway(settings: Settings | None = None) -> PaymentGateway:
    s = settings or get_settings()
    name = (s.PAYMENT_GATEWAY or "simulated").lower()
    if name == "simulated":
        return SimulatedPaymentGateway(s.PAYMENT_SIMULATE_SUCCESS_RATE)
    # Placeholders for future adapters; fall back to simulated to keep the
    # system usable while adapters are being implemented.
    return SimulatedPaymentGateway(s.PAYMENT_SIMULATE_SUCCESS_RATE)
