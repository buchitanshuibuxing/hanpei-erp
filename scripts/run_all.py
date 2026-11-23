"""一键回归入口：CI 与人工共用，按固定顺序跑完全部端到端测试与全链路冒烟。

用法（必须在 backend 目录下执行，测试脚本依赖 app 包可导入）：
    cd backend && python ../scripts/run_all.py
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SCRIPTS = ROOT / "scripts"

TESTS = [
    "test_quote_flow",
    "test_order_flow",
    "test_purchase_flow",
    "test_finance_flow",
    "test_stocktake_return",
    "test_closure_fixes",
    "test_v102_boundaries",
    "test_engineering_guards",
]
SMOKE = "smoke_api"


def main():
    failures = []
    for name in TESTS + [SMOKE]:
        script = SCRIPTS / f"{name}.py"
        print(f"\n=== {name} ===", flush=True)
        result = subprocess.run([sys.executable, str(script)], cwd=str(BACKEND))
        if result.returncode != 0:
            failures.append(name)
            print(f"!!! {name} FAILED (exit {result.returncode})", flush=True)
    if failures:
        print(f"\nREGRESSION FAILED: {', '.join(failures)}", flush=True)
        return 1
    print(f"\nREGRESSION PASSED: {len(TESTS)} suites + smoke all green", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
