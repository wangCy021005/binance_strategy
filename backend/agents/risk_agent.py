"""
Risk Agent — 三层风控（加密版）
知识库第15课：头寸→组合→系统三层防御

加密与A股的差异：
  - 波动率更高（正常年化80-120%），阈值相应放宽
  - 熔断冷静期用"小时"而非"天"（市场24/7）
  - 支持做空，风控需双向考虑
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger("crypto.risk")


class RiskLevel:
    NORMAL  = "NORMAL"
    WARN    = "WARN"
    STOP    = "STOP"
    CIRCUIT = "CIRCUIT"


@dataclass
class RiskDecision:
    approve:  bool
    size:     float
    reason:   str = ""


class RiskAgent:
    def __init__(self, cfg):
        self.cfg    = cfg
        self._peak  = cfg.cash
        self._circuit_until: datetime | None = None

    def get_level(self, portfolio_value: float) -> str:
        if portfolio_value > self._peak:
            self._peak = portfolio_value

        dd = (portfolio_value - self._peak) / self._peak

        if dd <= -self.cfg.dd_circuit:
            return RiskLevel.CIRCUIT
        if dd <= -self.cfg.dd_stop:
            return RiskLevel.STOP
        if dd <= -self.cfg.dd_warn:
            return RiskLevel.WARN
        return RiskLevel.NORMAL

    def trigger_circuit(self, now: datetime):
        cool_hours = getattr(self.cfg, 'circuit_cool_hours', 24)
        self._circuit_until = now + timedelta(hours=cool_hours)
        logger.warning("熔断触发！冷静期 %d 小时至 %s",
                        cool_hours, self._circuit_until.strftime("%Y-%m-%d %H:%M"))

    def in_cooldown(self, now: datetime) -> bool:
        if self._circuit_until is None:
            return False
        return now < self._circuit_until

    def check_order(self, size_pct: float, portfolio_value: float,
                    level: str, now: datetime) -> RiskDecision:
        """审核开仓请求"""
        if level == RiskLevel.CIRCUIT:
            if self.in_cooldown(now):
                return RiskDecision(False, 0, "熔断冷静期")
            # 冷静期结束，降格为 STOP
            level = RiskLevel.STOP

        if level == RiskLevel.STOP:
            # 只允许极小仓位试探
            cap = getattr(self.cfg, 'stop_position_cap', 0.05)
            size_pct = min(size_pct, cap)
            return RiskDecision(True, size_pct, f"STOP状态限仓{cap*100:.0f}%")

        if level == RiskLevel.WARN:
            scale = getattr(self.cfg, 'warn_pos_scale', 0.5)
            size_pct = size_pct * scale
            return RiskDecision(True, size_pct, f"WARN状态半仓")

        return RiskDecision(True, size_pct, "")
