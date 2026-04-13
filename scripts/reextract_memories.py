"""One-shot: re-extract facts from all chats of a given user.

Intended to be run inside the memory-service container:
    docker exec task-repo-memory-service-1 python /tmp/reextract_memories.py <user_id>
"""
import os, sys, json, asyncio, httpx, asyncpg


async def main(user_id: str):
    pg = os.environ["DATABASE_URL"].replace("postgresql+asyncpg", "postgresql").replace("/memory", "/openwebui")
    conn = await asyncpg.connect(pg)
    rows = await conn.fetch(
        "SELECT id, chat FROM chat WHERE user_id=$1 ORDER BY updated_at DESC",
        user_id,
    )
    await conn.close()
    print(f"chats: {len(rows)}")

    ok = fail = total = 0
    async with httpx.AsyncClient(timeout=180) as client:
        for r in rows:
            chat_id = r["id"]
            data = json.loads(r["chat"]) if isinstance(r["chat"], str) else r["chat"]
            msgs = data.get("messages", []) if isinstance(data, dict) else []
            clean = []
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                c = m.get("content")
                if isinstance(c, list):
                    c = "\n".join(
                        p.get("text", "") for p in c if isinstance(p, dict) and p.get("text")
                    )
                if isinstance(c, str) and c.strip():
                    clean.append({"role": m.get("role", "user"), "content": c})
            if len(clean) < 2:
                continue
            title = (data.get("title", "") or "")[:40]
            try:
                resp = await client.post(
                    "http://localhost:8000/memories/extract",
                    json={"user_id": user_id, "chat_id": chat_id, "messages": clean},
                )
                if resp.status_code == 200:
                    facts = resp.json()
                    n = len(facts) if isinstance(facts, list) else 0
                    total += n
                    ok += 1
                    print(f"  [{title:40s}] +{n}")
                else:
                    fail += 1
                    print(f"  [{title:40s}] HTTP {resp.status_code}: {resp.text[:120]}")
            except Exception as e:
                fail += 1
                print(f"  [{title:40s}] {type(e).__name__}: {e}")
    print(f"=== done: ok={ok} fail={fail} new_facts={total} ===")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
