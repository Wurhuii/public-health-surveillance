from __future__ import annotations

import argparse
import sys
import time


def _reconfigure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _format_elapsed(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:04.1f} ({seconds:.1f} 秒)"


def _print_result(coordinator, result, elapsed_seconds: float = None) -> None:
    summary = result.get("summary", {})
    print("=" * 60)
    print("  省级公共卫生风险监测多 Agent 系统 - 运行完成")
    print("=" * 60)
    print(f"  run_id:          {result.get('run_id', '')}")
    print(f"  统一事件数:      {summary.get('total_events', 0)}")
    print(f"  聚合时间点数:    {summary.get('aggregate_points', 0)}")
    print(f"  检测器输出点数:  {summary.get('detector_points', 0)}")
    print(f"  风险信号数:      {summary.get('risk_signals', 0)}")
    print(f"  风险等级分布:    {summary.get('risk_levels', {})}")
    exp = summary.get("explanation") or {}
    if exp:
        line = (
            f"  解释解析:        LLM生成 {exp.get('llm_generated', 0)}/{exp.get('drafts', 0)}，"
            f"解析成功率 {exp.get('llm_parse_success_rate', 0):.2%}"
        )
        lat = exp.get("latency")
        if lat:
            line += f"，单次延迟 avg {lat['avg_ms']}ms / p95 {lat['p95_ms']}ms"
        if not exp.get("llm_enabled"):
            line += "（LLM未启用）"
        print(line)
        drafts = coordinator.state.get("explanation_drafts", []) if hasattr(coordinator, "state") else []
        if exp.get("llm_enabled") and exp.get("llm_generated", 0) < exp.get("drafts", 0):
            for d in drafts:
                raw = d.get("raw_output")
                if raw:
                    print("  模型原始输出样例:", repr(raw[:300]))
                    break
    print(f"  自主性阶段:      {summary.get('autonomy_stage', '')}")
    print(f"  LangGraph模式:   {summary.get('use_langgraph', False)}")
    if elapsed_seconds is not None:
        print(f"  整个流程耗时:    {_format_elapsed(elapsed_seconds)}")
    print("=" * 60)


def cmd_run(args) -> None:
    started_at = time.monotonic()
    from .agent import MultiAgentCoordinator, run_with_langgraph
    from .config import load_config

    cfg = load_config(args.config) if args.config else load_config()
    coordinator = MultiAgentCoordinator(
        cfg=cfg,
        use_langgraph=args.langgraph,
        autonomy_stage=args.autonomy_stage,
    )

    if args.langgraph:
        try:
            result = run_with_langgraph(coordinator, inject=args.inject, shape=args.shape, magnitude=args.magnitude)
        except ImportError as exc:
            print(f"[WARN] LangGraph 不可用，回退到顺序编排: {exc}")
            result = coordinator.run(inject=args.inject, shape=args.shape, magnitude=args.magnitude)
    else:
        result = coordinator.run(inject=args.inject, shape=args.shape, magnitude=args.magnitude)

    _print_result(coordinator, result, time.monotonic() - started_at)


def cmd_serve(args) -> None:
    try:
        from .api.app import serve
        serve(args.host, args.port)
    except ImportError:
        from .api.fallback_server import serve
        serve(args.host, args.port)


def cmd_experiment(args) -> None:
    started_at = time.monotonic()
    import json

    from .config import PROJECT_ROOT
    from .research import RUNNERS

    runner = RUNNERS[args.rq]
    output = args.output or str(PROJECT_ROOT / "var" / f"{args.rq}_results.json")
    result = runner(output)
    summary = result.get("summary", result)
    print(f"[{args.rq}] 完成，结果写入: {output}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[{args.rq}] 整个实验耗时: {_format_elapsed(time.monotonic() - started_at)}")


def main(argv=None) -> None:
    _reconfigure_stdout()
    parser = argparse.ArgumentParser(prog="surveillance_agent", description="省级公共卫生风险监测多 Agent 系统")
    sub = parser.add_subparsers(dest="command")

    run_parser = sub.add_parser("run", help="运行一次完整监测流程")
    run_parser.add_argument("--inject", action="store_true", help="注入半合成异常")
    run_parser.add_argument("--shape", default="gradual", choices=["spike", "gradual", "cluster", "multimodal"])
    run_parser.add_argument("--magnitude", type=float, default=10.0)
    run_parser.add_argument("--langgraph", action="store_true", help="使用 Supervisor LangGraph 回环")
    run_parser.add_argument("--autonomy-stage", type=int, default=None, choices=[0, 1, 2, 3])
    run_parser.add_argument("--config", default="")

    serve_parser = sub.add_parser("serve", help="启动本地页面和 API")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8080)

    exp_parser = sub.add_parser("experiment", help="运行论文实验 (RQ1/RQ2/RQ4)")
    exp_parser.add_argument("rq", choices=["rq1", "rq2", "rq4"])
    exp_parser.add_argument("--output", default="")

    args = parser.parse_args(argv)
    if args.command == "run":
        cmd_run(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "experiment":
        cmd_experiment(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
