from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class PairOverride:
    src_index: int
    dst_index: int
    rate_bps: int
    priority: float = 1.0
    bidirectional: bool = True


@dataclass
class DemandProfile:
    default_rate_bps: int = 50_000_000
    default_priority: float = 1.0
    pair_overrides: List[PairOverride] = field(default_factory=list)

    @property
    def has_overrides(self) -> bool:
        return len(self.pair_overrides) > 0


def load_profile(path: str | Path) -> DemandProfile:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"Demand profile file not found: {target}")
    payload = json.loads(target.read_text())
    profile = DemandProfile(
        default_rate_bps=int(payload.get("default_rate_bps", DemandProfile.default_rate_bps)),
        default_priority=float(payload.get("default_priority", 1.0)),
    )
    for item in payload.get("ground_station_pairs", []):
        profile.pair_overrides.append(
            PairOverride(
                src_index=int(item["src_index"]),
                dst_index=int(item["dst_index"]),
                rate_bps=int(item.get("rate_bps", profile.default_rate_bps)),
                priority=float(item.get("priority", profile.default_priority)),
                bidirectional=bool(item.get("bidirectional", True)),
            )
        )
    return profile


def try_load_profile(path: Optional[str | Path]) -> Optional[DemandProfile]:
    if not path:
        return None
    return load_profile(path)
