"""staleness LLM 侧实验：真实语义判定器 + 回答质量验证（四策略对照）。

两项：
  A. LLMSimilarity：真实 LLM 判定两条记忆的关系（取代/精化/无关）→ 驱动折叠
  B. 回答质量：每轮组装后提问"用户当前偏好什么"+"怎么演化的"→ 正确率 × 可答率
预算：12 轮 × 4 策略（判定 1 次 + 回答 2 次）≈ 96 次 flash 调用 < $0.05。
"""

import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.environ.get(
    "PPB_SAMPLE_ROOT",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                 "PPBExt-Sample"))))
sys.path.insert(0, os.environ.get(
    "PPB_DECIDE_ROOT",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                 "PPBDec-Core"))))

from exocortex.adapter import GenRequest, adapter_from_config  # noqa: E402
from memorycore import (MemoryController, MemoryPage, MemoryStore,  # noqa: E402
                        PageKind, PromptComposer)

KEY = sys.argv[1] if len(sys.argv) > 1 else os.environ["DEEPSEEK_API_KEY"]
FLASH = adapter_from_config({"type": "openai", "base_url": "https://api.deepseek.com",
                             "api_key": KEY, "model": "deepseek-flash"})

EVOLUTION = [
    ("preference", "喜欢用 React 写前端"),
    ("preference", "喜欢用 React 写前端"),
    ("preference", "喜欢用 React 和 TypeScript"),
    ("preference", "改用 Svelte，觉得更简洁"),
    ("fact", "项目代号 Aurora"),
    ("preference", "Svelte 的响应式写法很顺手"),
    ("preference", "还是回 React 吧，生态更全"),
    ("fact", "部署在东京区"),
    ("preference", "React 的 hooks 需要多练习"),
    ("lesson", "前端选型不要只看简洁度"),
    ("preference", "接受 Vue 用于小型项目"),
    ("preference", "React 是主力，Vue 只做小工具"),
]

FRAMEWORKS = ["React", "Svelte", "Vue"]
CUR_FRAME = {1: "React", 2: "React", 3: "React", 4: "Svelte", 5: "Svelte",
             6: "Svelte", 7: "React", 8: "React", 9: "React", 10: "React",
             11: "React", 12: "React"}

SIM_PROMPT = ("判断以下两条用户记忆的关系，只输出 JSON："
              '{{"relation": "replace|refine|unrelated", "similarity": 0-1}}\n\n'
              "记忆A：{a}\n记忆B：{b}")


def llm_similarity(a: str, b: str) -> float:
    """真实语义判定：LLM 给出关系与相似度（取代/精化 → 高，无关 → 低）。"""
    if a == b:
        return 0.99   # 完全重复（省一次调用）
    g = FLASH.generate(GenRequest(
        messages=[{"role": "user", "content": SIM_PROMPT.format(a=a, b=b)}],
        max_tokens=200, thinking=False))
    txt = g.text
    try:
        j0, j1 = txt.find("{"), txt.rfind("}") + 1
        d = json.loads(txt[j0:j1])
        rel = d.get("relation", "unrelated")
        sim = float(d.get("similarity", 0.0))
        # 取代/精化 → 落在 UPDATE 折叠区间
        if rel in ("replace", "refine"):
            return min(max(sim, 0.6), 0.9)
        return min(sim, 0.3)
    except Exception:
        m = re.search(r'"similarity"\s*:\s*([0-9.]+)', txt)
        return float(m.group(1)) if m else 0.0


def ask_current(memory_text: str) -> str:
    g = FLASH.generate(GenRequest(
        messages=[{"role": "user", "content":
                   f"{memory_text}\n\n根据以上记忆，用户当前偏好用什么前端框架？只答一个词。"}],
        max_tokens=30, thinking=False))
    return g.text.strip()


def ask_evolution(memory_text: str) -> str:
    g = FLASH.generate(GenRequest(
        messages=[{"role": "user", "content":
                   f"{memory_text}\n\n根据以上记忆，用户的偏好在最近几轮是怎么变化的？一句话。"}],
        max_tokens=80, thinking=False))
    return g.text.strip()


def run(strategy: str) -> dict:
    store = MemoryStore()
    comp = PromptComposer(kind_budgets={"preference": 300, "decision": 100,
                                        "fact": 200, "lesson": 150},
                          stability_threshold=0.5)
    dc = None
    from decisioncore import DecisionCore
    dc = DecisionCore()
    ctl = MemoryController(store, dc=dc,
                           similarity_fn=llm_similarity if strategy == "fold_llm" else None)

    rows = []
    for i, (kind, content) in enumerate(EVOLUTION, 1):
        if strategy == "naive":
            store.add(MemoryPage(kind=kind, content=content))
        elif strategy == "delete":
            if kind == "preference":
                store.pages = [p for p in store.pages if p.kind != kind]
            store.add(MemoryPage(kind=kind, content=content))
        elif strategy == "fold_char":
            ctl.ingest(PageKind(kind), content)
        else:  # fold_llm
            ctl.ingest(PageKind(kind), content)

        r = comp.compose(store.active_pages())
        cur = CUR_FRAME[i]
        ans = ask_current(r.text) if r.text else ""
        correct = cur.lower() in ans.lower()
        evo = ask_evolution(r.text) if r.text and i >= 4 else ""
        # 追问可答：回答里提到 >=2 个不同框架（说明能说出演化）
        evo_ok = len({f for f in FRAMEWORKS if f.lower() in evo.lower()}) >= 2
        rows.append({"turn": i, "cur": cur, "ans": ans[:20], "correct": correct,
                     "evo_ok": evo_ok, "prefix_overlap": r.prefix_overlap,
                     "n_active": len(store.active_pages()),
                     "fold_pages": store.stats()["fold_pages"]})
        time.sleep(0.15)

    n_correct = sum(1 for x in rows if x["correct"])
    evo_rows = [x for x in rows if x["turn"] >= 4]
    n_evo = sum(1 for x in evo_rows if x["evo_ok"])
    overlaps = [x["prefix_overlap"] for x in rows if x["prefix_overlap"] is not None]
    return {
        "strategy": strategy,
        "answer_accuracy": round(n_correct / len(rows), 3),
        "evolution_answerable": round(n_evo / max(len(evo_rows), 1), 3),
        "avg_prefix_overlap": round(sum(overlaps) / len(overlaps), 3) if overlaps else 0,
        "final_active": rows[-1]["n_active"],
        "fold_pages": rows[-1]["fold_pages"],
        "audited": sum(1 for a in ctl.actions if a.decision_id) if strategy.startswith("fold") else 0,
        "rows": rows,
    }


def main() -> None:
    print("=" * 76)
    print("staleness LLM 侧实验：回答正确率 × 追问可答率 × 缓存代价（12 轮演化）")
    print("=" * 76)
    results = []
    for s in ["naive", "delete", "fold_char", "fold_llm"]:
        print(f"\n跑策略 {s} ...", flush=True)
        r = run(s)
        results.append(r)
        print(f"  正确率={r['answer_accuracy']} 追问可答={r['evolution_answerable']} "
              f"前缀重合={r['avg_prefix_overlap']} 折叠页={r['fold_pages']} "
              f"审计={r['audited']}")

    print("\n" + "=" * 76)
    print(f"{'策略':11s} {'回答正确':>8s} {'追问可答':>8s} {'前缀重合':>8s} "
          f"{'折叠页':>6s} {'审计':>5s}")
    for r in results:
        print(f"{r['strategy']:11s} {r['answer_accuracy']:>8.2f} "
              f"{r['evolution_answerable']:>8.2f} {r['avg_prefix_overlap']:>8.2f} "
              f"{r['fold_pages']:>6d} {r['audited']:>5d}")

    os.makedirs("results", exist_ok=True)
    with open("results/staleness_llm_experiment.json", "w", encoding="utf-8") as f:
        json.dump({"results": [{k: v for k, v in r.items() if k != "rows"}
                               for r in results],
                   "detail": {r["strategy"]: r["rows"] for r in results}},
                  f, ensure_ascii=False, indent=2)
    print("SAVED results/staleness_llm_experiment.json")


if __name__ == "__main__":
    main()
