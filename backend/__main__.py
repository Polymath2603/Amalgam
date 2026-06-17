"""
Amalgam CLI — usage: python -m backend <command>

Commands:
  stats [--days N]    Show cost/usage statistics for the last N days (default: 7)
  curate              Run skill curator manually (grades, archives, merges skills)
  server              Start the FastAPI server (default if no command given)
"""

import sys
import asyncio


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        days = 7
        if "--days" in sys.argv:
            idx = sys.argv.index("--days")
            days = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 7
        asyncio.run(_print_stats(days))
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "curate":
        asyncio.run(_run_curator())
        sys.exit(0)

    # Default: run server
    import uvicorn
    uvicorn.run(
        "backend.app:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="warning",
    )


async def _print_stats(days: int):
    from backend.core.metrics import get_collector

    collector = get_collector()
    r = await collector.report(days=days)
    W = 52
    print()
    print("=" * W)
    print(f"  Amalgam — Last {days} Day{'s' if days != 1 else ''}")
    print("=" * W)
    print(f"  Turns:          {r['total_turns']}")
    print(f"  Cost:           ${r['total_cost_usd']:.4f} USD")
    print(f"  Tokens:         {r['total_tokens']:,}")
    print(f"  Avg latency:    {r['avg_latency_ms']:.0f} ms")
    print(f"  Tool calls:     {r['total_tool_calls']}")
    print(f"  Avg mem hits:   {r['avg_memory_hits_per_turn']:.1f}/turn")
    if r.get("top_models"):
        print(f"\n  Models:")
        for m in r["top_models"]:
            print(f"    {m['model']:<32} {m['uses']:>4} turns  ${m['cost']:.4f}")
    if r.get("top_skills"):
        print(f"\n  Skills:")
        for s in r["top_skills"]:
            print(f"    {s['skill_used']:<32} {s['uses']:>4} uses")
    print()


async def _run_curator():
    """Run the skill curator manually."""
    from backend.core.skills.curator import SkillCurator
    from backend.core.metrics import get_collector

    collector = get_collector()
    curator = SkillCurator(metrics_collector=collector)
    await curator.run()


if __name__ == "__main__":
    main()
