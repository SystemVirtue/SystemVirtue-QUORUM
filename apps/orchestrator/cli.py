import argparse
import asyncio
from app.core.schemas import SystemVirtueOptions
from app.pipeline.quorum import run_quorum
from app.registry.openrouter import FreeModelRegistry


async def main() -> None:
    parser = argparse.ArgumentParser(description="System Virtue QUORUM CLI prototype")
    parser.add_argument("prompt", nargs="+", help="Coding/debugging/architecture prompt")
    parser.add_argument("--mode", default="balanced", choices=["fast", "balanced", "deep", "adversarial", "auditor"])
    args = parser.parse_args()

    registry = FreeModelRegistry()
    await registry.refresh()
    result = await run_quorum(" ".join(args.prompt), args.mode, SystemVirtueOptions(), registry)
    print("# System Virtue QUORUM Report")
    print()
    print(f"- Mode: {result.metadata['mode']}")
    print(f"- Consensus score: {result.metadata['consensus_score']}")
    print(f"- Marginal cost: ${result.metadata['marginal_cost_usd']:.2f}")
    print()
    print("## Council")
    for member in result.metadata["council"]:
        print(f"- {member['label']}: {member['model']} as {member['role']} ({member['model_class']})")
    print()
    print("## Final")
    print(result.final_answer)


if __name__ == "__main__":
    asyncio.run(main())
