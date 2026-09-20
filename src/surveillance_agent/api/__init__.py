from __future__ import annotations

from typing import Any, Dict, Optional


def _run_once(
    inject: bool = False,
    shape: str = "gradual",
    magnitude: float = 10.0,
    use_langgraph: bool = False,
    autonomy_stage: Optional[int] = None,
) -> Dict[str, Any]:
    from ..agent import MultiAgentCoordinator, run_with_langgraph
    from ..config import load_config

    cfg = load_config()
    coordinator = MultiAgentCoordinator(
        cfg=cfg,
        use_langgraph=use_langgraph,
        autonomy_stage=autonomy_stage,
    )
    if use_langgraph:
        try:
            return run_with_langgraph(coordinator, inject=inject, shape=shape, magnitude=magnitude)
        except ImportError:
            return coordinator.run(inject=inject, shape=shape, magnitude=magnitude)
    return coordinator.run(inject=inject, shape=shape, magnitude=magnitude)
