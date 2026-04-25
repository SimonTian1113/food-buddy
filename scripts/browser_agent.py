#!/usr/bin/env python3
"""
FoodBuddy Browser Agent — 浏览器任务执行器

职责：
  1. 读取 Skill 写入的 .browser_tasks/ 任务文件
  2. 用 Playwright 模拟浏览器，抓取动态页面（OpenRice / 小红书 等）
  3. 提取结构化数据（评分、评论数、地址、价格等）
  4. 将结果写回 .browser_results/，供 Skill 读取合并

运行方式：
  单次执行：  python3 scripts/browser_agent.py
  守护进程：  python3 scripts/browser_agent.py --daemon --interval 30

依赖安装：
  pip install playwright
  playwright install chromium
"""

import argparse
import json
import time
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
TASKS_DIR = SKILL_DIR / ".browser_tasks"
RESULTS_DIR = SKILL_DIR / ".browser_results"

# ===== 平台提取配置 =====
# 每个平台定义：如何构造搜索 URL、目标域名、页面内 CSS 选择器
PLATFORM_CONFIG = {
    "openrice": {
        "domains": ["openrice.com"],
        "search_template": "https://www.bing.com/search?q=site:openrice.com+{query}",
        "page_wait_ms": 3000,
        "selectors": {
            "rating": ".score-div, .rating-score, .header-score, [class*='score']",
            "review_count": ".review-count, .comment-count, [class*='review']",
            "price_range": ".price-range, .avg-price, [class*='price']",
            "address": ".address, [class*='address']",
            "phone": ".tel, [class*='phone'], [class*='tel']",
        },
    },
    "xiaohongshu": {
        "domains": ["xiaohongshu.com"],
        "search_template": "https://www.bing.com/search?q=site:xiaohongshu.com+{query}",
        "page_wait_ms": 3000,
        "selectors": {
            "title": "h1, .title, [class*='title']",
            "likes": ".like-count, [class*='like'], [class*='collect']",
            "author": ".author-name, [class*='author']",
            "content_snippet": ".content, .note-content, [class*='content']",
        },
    },
}


def _build_result_item(url: str, title: str, snippet: str, extracted: dict) -> dict:
    """构造标准格式的结果条目。"""
    return {
        "title": title or "无标题",
        "url": url,
        "snippet": snippet,
        "score": 0.6,
        "source": "browser_agent",
        "_browser_extracted": extracted,
    }


def process_task(task: dict) -> list:
    """
    处理单个浏览器任务。
    返回标准格式的结果列表 [{title, url, snippet, score, source}, ...]
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ❌ Playwright 未安装。请运行: pip install playwright && playwright install chromium")
        return []

    platform = task.get("platform")
    query = task.get("query", "")
    max_results = task.get("max_results", 8)
    config = PLATFORM_CONFIG.get(platform, {})

    if not config:
        print(f"  ⚠️ 未知平台: {platform}，跳过")
        return []

    results = []
    domains = config.get("domains", [])
    search_url = config.get("search_template", "").format(query=query.replace(" ", "+"))
    page_wait_ms = config.get("page_wait_ms", 3000)

    with sync_playwright() as p:
        # 启动无头浏览器
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            # === Step 1: 搜索引擎找目标平台链接 ===
            print(f"  🔍 搜索: {search_url}")
            page.goto(search_url, wait_until="networkidle", timeout=20000)
            time.sleep(1)

            # 从搜索结果中提取目标平台链接
            target_links = []
            for a in page.query_selector_all("li.b_algo a[href]"):
                href = a.get_attribute("href") or ""
                if any(d in href for d in domains):
                    title = a.inner_text().strip()[:100]
                    target_links.append({"url": href, "title": title})
                    if len(target_links) >= max_results:
                        break

            if not target_links:
                print(f"  ⚠️ 未在搜索结果中找到 {platform} 链接")
                browser.close()
                return []

            # === Step 2: 逐个打开目标页面，提取数据 ===
            for link_info in target_links:
                url = link_info["url"]
                print(f"  🌐 打开: {url}")
                try:
                    page.goto(url, wait_until="networkidle", timeout=20000)
                    time.sleep(page_wait_ms / 1000)  # 等 JS 渲染

                    # 提取页面标题
                    title = page.title() or link_info["title"]

                    # 用选择器提取结构化字段
                    extracted = {}
                    for field, selector in config.get("selectors", {}).items():
                        try:
                            elem = page.query_selector(selector)
                            if elem:
                                text = elem.inner_text().strip()
                                if text:
                                    extracted[field] = text[:200]
                        except Exception:
                            pass

                    # 构造 snippet（拼接提取到的关键字段）
                    snippet_parts = []
                    if "rating" in extracted:
                        snippet_parts.append(f"评分: {extracted['rating']}")
                    if "review_count" in extracted:
                        snippet_parts.append(f"评论数: {extracted['review_count']}")
                    if "price_range" in extracted:
                        snippet_parts.append(f"人均: {extracted['price_range']}")
                    if "address" in extracted:
                        snippet_parts.append(f"地址: {extracted['address']}")
                    snippet = " | ".join(snippet_parts) if snippet_parts else title

                    results.append(_build_result_item(url, title, snippet, extracted))
                    print(f"  ✅ 提取成功: {title[:50]}")

                except Exception as e:
                    print(f"  ⚠️ 打开页面失败: {e}")
                    continue

        except Exception as e:
            print(f"  ❌ 任务处理异常: {e}")
        finally:
            browser.close()

    return results


def run_once() -> int:
    """
    单次扫描并处理所有待处理任务。
    返回处理成功的任务数量。
    """
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    task_files = sorted(TASKS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not task_files:
        print("📭 无待处理浏览器任务")
        return 0

    processed = 0
    for task_file in task_files:
        print(f"\n📂 处理任务: {task_file.name}")
        try:
            task = json.loads(task_file.read_text(encoding="utf-8"))
            results = process_task(task)

            if results:
                # 写入结果文件（文件名与任务文件对应，方便追溯）
                result_file = RESULTS_DIR / task_file.name
                result_file.write_text(
                    json.dumps({"results": results}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"  💾 结果已写入: {result_file}")
                processed += 1
            else:
                print(f"  ⚠️ 未提取到有效数据")

            # 无论成功与否，删除已处理的任务文件（避免重复处理）
            task_file.unlink()

        except Exception as e:
            print(f"  ❌ 读取任务文件失败: {e}")
            # 读取失败也删除，避免死循环
            try:
                task_file.unlink()
            except Exception:
                pass

    return processed


def run_daemon(interval: int = 30):
    """守护进程模式：定期轮询任务目录。"""
    print(f"🤖 Browser Agent 守护进程已启动，轮询间隔: {interval} 秒")
    print(f"   任务目录: {TASKS_DIR}")
    print(f"   结果目录: {RESULTS_DIR}")
    print("   按 Ctrl+C 停止\n")

    while True:
        try:
            count = run_once()
            if count == 0:
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n👋 守护进程已停止")
            break
        except Exception as e:
            print(f"\n❌ 守护进程异常: {e}")
            time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="FoodBuddy 浏览器任务执行器")
    parser.add_argument("--daemon", action="store_true", help="以守护进程模式运行")
    parser.add_argument("--interval", type=int, default=30, help="守护进程轮询间隔（秒）")
    args = parser.parse_args()

    if args.daemon:
        run_daemon(interval=args.interval)
    else:
        count = run_once()
        print(f"\n🏁 完成，处理任务数: {count}")


if __name__ == "__main__":
    main()
