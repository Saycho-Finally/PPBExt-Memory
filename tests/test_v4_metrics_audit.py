"""v0.4 测试：块级命中率指标（M3）与删除审计链（M4）。

M3 关注"命中率怎么算才有诊断力"——块级与字符级必须分开看；
M4 关注"删除怎么证明"——审计记录只存哈希，且记录本身可验真。
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from memorycore import (AuditEvent, MemoryPage, MemoryStore,  # noqa: E402
                        PageKind, HitRateTracker, append_event, audit_report,
                        block_metric, collect_purge_events, hash_content,
                        verify_chain)

RESULTS = []


def check(name, cond, note=""):
    s = "PASS" if cond else "FAIL"
    RESULTS.append((name, s))
    print(f"  [{s}] {name}" + (f" ---- {note}" if note else ""))


def test_block_metric():
    print("M3：块级 vs 字符级")
    m = block_metric(None, "x" * 600, chars_per_block=256)
    check("首次无上一轮 → 命中率 0", m.block_hit_rate == 0.0
          and m.token_hit_rate == 0.0)
    check("完整块数 = 600//256 = 2（尾块不缓存，不入分母）",
          m.total_blocks == 2, str(m.total_blocks))
    check("尾部不足一块的字符数被单独报告", m.partial_tail == 600 - 512,
          str(m.partial_tail))

    same = block_metric("x" * 600, "x" * 600, chars_per_block=256)
    check("完全相同 → 块级 1.0", same.block_hit_rate == 1.0
          and same.token_hit_rate == 1.0, f"block={same.block_hit_rate}")

    # 分歧落在不可缓存的尾块内：可缓存块全中，损失只在尾部
    tail = block_metric("x" * 600, "x" * 550 + "y" * 50, chars_per_block=256)
    check("尾块内分歧：块级仍 1.0（可缓存块全中）",
          tail.block_hit_rate == 1.0, str(tail.block_hit_rate))
    check("尾块内分歧：字符级 < 1.0（暴露尾部损失）",
          tail.token_hit_rate < 1.0, str(tail.token_hit_rate))
    check("尾部变化：前缀未被动过", tail.prefix_changed is False)
    check("尾部浪费 > 0", tail.tail_waste > 0, str(tail.tail_waste))

    # 前缀被改动（首个块内就分歧）→ 缓存杀手
    head = block_metric("A" * 600, "B" + "A" * 599, chars_per_block=256)
    check("首块内分歧 → 前缀被动过且块级归零",
          head.prefix_changed is True and head.block_hit_rate == 0.0)

    beyond = block_metric("x" * 600, "x" * 300 + "y" * 300, chars_per_block=256)
    check("分歧越过第一个块 → 块级下降", beyond.block_hit_rate == 0.5,
          str(beyond.block_hit_rate))


def test_tracker():
    print("M3：会话汇总")
    t = HitRateTracker(chars_per_block=256, low_rate_threshold=0.5)
    t.observe("a" * 600)
    t.observe("a" * 600)
    t.observe("a" * 610)
    s = t.summary()
    check("轮次计数", s["turns"] == 3)
    check("前缀未被破坏", s["prefix_breaks"] == 0, str(s["prefix_breaks"]))
    check("均值在 0-1 之间", 0.0 <= s["mean_block_hit_rate"] <= 1.0,
          str(s["mean_block_hit_rate"]))
    check("尾部浪费累计", s["total_tail_waste"] > 0)
    t2 = HitRateTracker(chars_per_block=64)
    t2.observe("x" * 300)
    t2.observe("y" * 300)
    check("前缀被换掉 → prefix_breaks=1", t2.summary()["prefix_breaks"] == 1)


def test_chain_build():
    print("M4：哈希链构建")
    ev = []
    append_event(ev, "delete", "p1", "内容一", reason="用户要求", ts=1.0)
    append_event(ev, "purge", "p2", "内容二", reason="过期", ts=2.0)
    check("两条事件序号连续", [e.seq for e in ev] == [0, 1])
    check("首条 prev 为创世值", ev[0].prev_hash == "0" * 16)
    check("后一条 prev 衔接前一条",
          ev[1].prev_hash == ev[0].this_hash)
    check("事件只存哈希不存内容",
          all("内容" not in e.content_hash for e in ev)
          and hash_content("内容一") == ev[0].content_hash)
    ok, why = verify_chain(ev)
    check("完整链校验通过", ok, why)


def test_chain_tamper():
    print("M4：篡改必须被检出")
    def fresh():
        ev = []
        append_event(ev, "delete", "p1", "内容一", reason="r1")
        append_event(ev, "delete", "p2", "内容二", reason="r2")
        return ev

    ev = fresh()
    ev[0].page_id = "p9"
    check("改 page_id → 失败", verify_chain(ev)[0] is False, verify_chain(ev)[1])

    ev = fresh()
    ev[1].content_hash = "deadbeefdeadbeef"
    check("改 content_hash → 失败", verify_chain(ev)[0] is False)

    ev = fresh()
    ev[0].reason = "改过的理由"
    check("改 reason → 失败", verify_chain(ev)[0] is False)

    ev = fresh()
    del ev[0]
    check("删除中间事件 → 失败", verify_chain(ev)[0] is False,
          verify_chain(ev)[1])


def test_report_and_store():
    print("M4：可验证输出与实库解析")
    rep = audit_report([])
    check("空链报告合法", rep["chain_ok"] is True
          and rep["n_events"] == 0 and rep["content_retained"] is False)

    store = MemoryStore()
    for i in range(3):
        store.add(MemoryPage(kind=PageKind.FACT.value, content=f"记忆条目 {i}"))
    ids = [p.page_id for p in store.pages]
    store.purge(ids[0], reason="用户要求")
    store.purge(ids[1], reason="过期")
    events = collect_purge_events(store.pages)
    check("从实库解析出 2 条 purge 事件", len(events) == 2)
    check("解析出的页面 id 正确",
          {e.page_id for e in events} == {ids[0], ids[1]})
    r = audit_report(events)
    check("实库审计链校验通过", r["chain_ok"] is True, r["chain_error"])
    check("报告含链头与事件明细",
          len(r["head_hash"]) > 0 and len(r["events"]) == 2)
    check("被删内容不在审计输出中",
          all("记忆条目" not in str(e) for e in r["events"]))


if __name__ == "__main__":
    print("=" * 64)
    print("PPBExt-Memory v0.4：块级命中率指标 + 删除审计链")
    print("=" * 64)
    test_block_metric()
    test_tracker()
    test_chain_build()
    test_chain_tamper()
    test_report_and_store()
    print("=" * 64)
    n_pass = sum(1 for r in RESULTS if r[1] == "PASS")
    print(f"总计：{n_pass}/{len(RESULTS)} PASS")
    print("MEM_V4_OK" if n_pass == len(RESULTS) else "MEM_V4_FAIL")
    sys.exit(0 if n_pass == len(RESULTS) else 1)
