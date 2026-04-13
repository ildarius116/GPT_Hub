"""E2E check: mws_memory inlet → mws_auto_router pipe → real LiteLLM response.

Run inside openwebui container where both files live and env vars are set:
    docker cp scripts/e2e_memory_test.py task-repo-openwebui-1:/tmp/e2e.py
    docker exec task-repo-openwebui-1 python /tmp/e2e.py
"""
import asyncio
import importlib.util
import os
import sys


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


async def main():
    # These two files are mounted into openwebui container via docker-compose
    mem_mod = _load("/tmp/memory_function.py", "memory_function")
    auto_mod = _load("/tmp/auto_router_function.py", "auto_router_function")

    mem_filter = mem_mod.Filter()
    auto_pipe = auto_mod.Pipe()

    USER = {"id": "0b23c315-978e-4a2f-bca0-ed1bad206b19", "name": "ildarius"}
    body = {
        "model": "mws_auto_router.mws-auto",
        "messages": [{"role": "user", "content": "как меня зовут?"}],
        "stream": False,
    }

    # Step 1: inlet injects memory facts
    body = mem_filter.inlet(body, __user__=USER)
    sys_msgs = [m for m in body["messages"] if m.get("role") == "system"]
    print("=== after inlet ===")
    for m in sys_msgs:
        print(m["content"][:500])
    print()

    # Step 2: pipe runs auto-router and aggregator
    print("=== pipe output ===")
    full = []
    async for chunk in auto_pipe.pipe(body, __user__=USER):
        sys.stdout.write(chunk)
        sys.stdout.flush()
        full.append(chunk)
    print("\n=== done ===")


if __name__ == "__main__":
    asyncio.run(main())
