import csv
import os
from typing import Optional

from loguru import logger


class LinkFailureManager:
    """按链路连通矩阵注入随机性中断。

    CSV 格式：第一列为链路名（如 "NODE_0_1 -> NODE_0_0"），其余列 T_0..T_N 为
    每个时间步的连通值。0 表示中断，非 0 表示不中断。每次调用 step() 推进一格。
    超出最后一列后保持在最后一列（即不再变化）。
    """

    def __init__(self, csv_path: str):
        self._enabled = False
        self._matrix: dict[frozenset[str], list[int]] = {}
        self._total_steps = 0
        self._step = 0
        self._last_down: set[frozenset[str]] = set()

        if not csv_path or not os.path.isfile(csv_path):
            logger.warning("链路故障矩阵不存在: {}，禁用故障注入。", csv_path)
            return

        with open(csv_path, "r", newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                logger.warning("链路故障矩阵为空: {}", csv_path)
                return
            self._total_steps = max(0, len(header) - 1)
            for row in reader:
                if not row or not row[0].strip():
                    continue
                name = row[0].strip()
                key = self._parse_pair(name)
                if key is None:
                    logger.warning("无法解析链路矩阵行名: {}", name)
                    continue
                values: list[int] = []
                for cell in row[1:]:
                    cell = cell.strip()
                    try:
                        values.append(int(float(cell)) if cell else 1)
                    except ValueError:
                        values.append(1)
                self._matrix[key] = values

        self._enabled = bool(self._matrix) and self._total_steps > 0
        logger.info(
            "链路故障矩阵加载完成: 链路={} 时间步={} 启用={}",
            len(self._matrix), self._total_steps, self._enabled,
        )
        if self._enabled:
            self._log_transitions()

    @staticmethod
    def _parse_pair(name: str) -> Optional[frozenset[str]]:
        for sep in ("->", "→", "--"):
            if sep in name:
                a, b = name.split(sep, 1)
                a, b = a.strip(), b.strip()
                if a and b:
                    return frozenset((a, b))
                return None
        return None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def step_index(self) -> int:
        return self._step

    def advance(self) -> None:
        if not self._enabled:
            return
        if self._step < self._total_steps - 1:
            self._step += 1
        self._log_transitions()

    def is_link_up(self, instance_a: str, instance_b: str) -> bool:
        """矩阵未覆盖的链路视为不中断 (返回 True)。"""
        if not self._enabled:
            return True
        values = self._matrix.get(frozenset((instance_a, instance_b)))
        if values is None:
            return True
        idx = min(self._step, len(values) - 1)
        return values[idx] != 0

    def _log_transitions(self) -> None:
        current_down: set[frozenset[str]] = set()
        for key, values in self._matrix.items():
            idx = min(self._step, len(values) - 1)
            if values[idx] == 0:
                current_down.add(key)

        new_down = current_down - self._last_down
        recovered = self._last_down - current_down
        for key in sorted(new_down, key=lambda k: sorted(k)):
            a, b = sorted(key)
            logger.warning(
                "[link-failure] t={} 链路中断: {} <-> {}", self._step, a, b,
            )
        for key in sorted(recovered, key=lambda k: sorted(k)):
            a, b = sorted(key)
            # logger.info(
            #     "[link-failure] t={} 链路恢复: {} <-> {}", self._step, a, b,
            # )
        if current_down:
            logger.info(
                "[link-failure] t={} 当前中断数={}", self._step, len(current_down),
            )
        self._last_down = current_down

    # def is_link_up(self, instance_a: str, instance_b: str) -> bool:
    #     """矩阵未覆盖的链路视为不中断 (返回 True)。"""
    #     if not self._enabled:
    #         return True
    #     values = self._matrix.get(frozenset((instance_a, instance_b)))
    #     if values is None:
    #         return True
    #     idx = min(self._step, len(values) - 1)
    #     return values[idx] != 0

    # def get_current_interruptions(self) -> set[frozenset[str]]:
    #     """返回当前时间步中故障矩阵标记为中断的所有链路集合。"""
    #     if not self._enabled:
    #         return set()
    #     result: set[frozenset[str]] = set()
    #     for key, values in self._matrix.items():
    #         idx = min(self._step, len(values) - 1)
    #         if values[idx] == 0:
    #             result.add(key)
    #     return result