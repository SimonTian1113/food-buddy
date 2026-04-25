#!/usr/bin/env python3
"""
食通天 MVP 编排器
聚焦：从网上种草到出发前验证单家餐厅是否值得去

运行方式：
  python3 scripts/orchestrator.py

由 OpenClaw Agent 调用，使用内置搜索和 LLM 能力。
"""

import os
import re
import json
from pathlib import Path
from urllib.parse import urlparse

SKILL_DIR = Path(__file__).parent.parent
PROMPTS_DIR = SKILL_DIR / "prompts"

CITIES = {
    "香港": "hongkong",
    "Hong Kong": "hongkong",
    "hk": "hongkong",
    "曼谷": "bangkok",
    "Bangkok": "bangkok",
    "bkk": "bangkok",
    "东京": "tokyo",
    "Tokyo": "tokyo",
    "首尔": "seoul",
    "Seoul": "seoul",
}

TAVILY_API_URL = "https://api.tavily.com/search"
PLATFORM_DISPLAY_NAMES = {
    "google_maps": "Google Maps",
    "dianping": "大众点评",
    "xiaohongshu": "小红书",
    "openrice": "OpenRice",
}
PLATFORM_DOMAINS = {
    "google_maps": ["google.com", "maps.google.com"],
    "dianping": ["dianping.com", "m.dianping.com"],
    "xiaohongshu": ["xiaohongshu.com", "www.xiaohongshu.com"],
    "openrice": ["openrice.com"],
}
# ===== 标题级过滤：聚合页 / 列表页 / 非目标店专属内容 =====
BAD_TITLE_HINTS = [
    # 聚合/列表类
    "排行榜", "合集", "推荐", "攻略", "大全",
    "Top", "top", "TOP", "必吃榜", "必去", "种草",
    # 低质聚合站
    "知乎", "马蜂窝", "豆丁", "本地宝", "今日头条",
    "百家号", "搜狐", "网易号", "企鹅号", "大鱼号",
]

# ===== 营销话术关键词：标题或 snippet 中出现 = 高概率是营销内容 =====
MARKETING_BUZZWORDS = [
    # 夸张热度
    "全网爆火", "刷爆", "火爆全", "排队几小时", "排队x小时",
    "一座难求", "黄牛票", "凌晨", "天没亮就",
    # 模板化夸赞
    "绝绝子", "绝了", "yyds", "封神", "天花板", "必吃",
    "不踩雷", "零差评", "无差评", "回头客无数",
    # 种草套路
    "宝藏店铺", "宝藏小店", "隐藏款", "本地人不知道",
    "只有本地人知道", "游客不知道", "不去后悔",
    "去了还想再去", "每次来必点",
    # 小红书体
    "家人们", "姐妹们", "集美们", "真的绝", "谁懂啊",
    "狠狠爱住", "氛围感拉满", "出片率",
]
# 简短版（用于 snippet 快速扫描，避免误伤正常描述）
MARKETING_SNIPPET_SHORT = [
    "绝绝子", "yyds", "封神", "天花板", "绝了",
    "家人们", "姐妹们", "谁懂啊", "狠狠爱",
    "不踩雷", "零差评", "无差评",
    "必吃", "宝藏", "不去后悔",
]

# ===== URL 域名黑名单：这些站的内容不作为有效证据 =====
BAD_DOMAINS = [
    # SEO 农场 / 内容搬运
    "zhihu.com",          # 知乎问答（多为个人主观，非平台评分）
    "mafengwo.cn",        # 马蜂窝攻略（聚合型）
    "sohu.com",           # 搜狐号
    "163.com",            # 网易号
    "qq.com",             # 企鹅号（非大众点评主站）
    "baidu.com",          # 百度经验/文库等
    "toutiao.com",        # 今日头条
    "baijiahao.baidu.com",# 百家号
    # 其他低质聚合
    "douban.com",         # 豆瓣小组（非结构化点评）
    "bendibao.com",       # 本地宝
    # AI 生成 / 搬运站（持续补充）
]
# 域名白名单：即使 snippet 有营销词，这些域名仍可信（保留作为证据）
TRUSTED_DOMAINS = [
    "google.com", "maps.google.com",     # Google Maps
    "dianping.com", "m.dianping.com",     # 大众点评
    "xiaohongshu.com",                    # 小红书（本身有营销属性但需要原始信号）
    "openrice.com",                       # OpenRice
    "tripadvisor.com",                    # TripAdvisor
    "yelp.com",                           # Yelp
]

CHAIN_HINTS = ["分店", "branch", "店", "soho", "wan chai", "中环", "沙田", "湾仔", "铜锣湾", "九龙", "尖沙咀"]


# ===== 搜索策略配置 =====
# 所有平台统一走浏览器搜索（更稳定），无浏览器时回退静态爬虫
PLATFORM_KEYWORDS = {
    "google_maps":  ["google maps", "google", "maps.google"],
    "tripadvisor":  ["tripadvisor", "猫途鹰"],
    "dianping":     ["dianping", "大众点评", "点评"],
    "openrice":     ["openrice", "开饭喇"],
    "xiaohongshu":  ["xiaohongshu", "小红书", "xhs"],
}


def _has_browser_tool() -> dict:
    """
    检测系统中有哪些浏览器工具可用。
    返回: {
        "has_playwright": bool,      # Python playwright 库
        "has_browser_use": bool,     # browser-use CLI
        "has_playwright_cli": bool,  # playwright-cli (clawbrowser)
        "has_stagehand": bool,       # stagehand-browser-cli
        "any": bool,                 # 是否有任意浏览器工具
        "recommended": str,          # 推荐使用的工具名称
    }
    """
    import shutil
    result = {
        "has_playwright": False,
        "has_browser_use": False,
        "has_playwright_cli": False,
        "has_stagehand": False,
        "any": False,
        "recommended": "",
    }

    # 检测 Python playwright 库
    try:
        from playwright.sync_api import sync_playwright
        result["has_playwright"] = True
    except ImportError:
        pass

    # 检测 browser-use CLI
    if shutil.which("browser-use") or shutil.which("bu"):
        result["has_browser_use"] = True

    # 检测 playwright-cli (clawbrowser)
    if shutil.which("playwright-cli"):
        result["has_playwright_cli"] = True

    # 检测 stagehand-browser-cli
    if shutil.which("browser"):
        # 需要确认是 stagehand 的 browser，不是系统自带的
        try:
            import subprocess
            output = subprocess.run(["browser", "--version"], capture_output=True, text=True, timeout=5)
            if "stagehand" in output.stdout.lower() or "browser" in output.stdout.lower():
                result["has_stagehand"] = True
        except Exception:
            pass

    result["any"] = any([
        result["has_playwright"],
        result["has_browser_use"],
        result["has_playwright_cli"],
        result["has_stagehand"],
    ])

    # 推荐优先级: playwright > browser-use > playwright-cli > stagehand
    if result["has_playwright"]:
        result["recommended"] = "playwright"
    elif result["has_browser_use"]:
        result["recommended"] = "browser-use"
    elif result["has_playwright_cli"]:
        result["recommended"] = "playwright-cli"
    elif result["has_stagehand"]:
        result["recommended"] = "stagehand"

    return result


def _search_browser(query: str, max_results: int = 8, city: str = None) -> list:
    """
    浏览器搜索：用 Playwright 打开 Bing 搜索页面，提取真实搜索结果。
    比静态爬虫更稳定，能正确渲染 JS 和中文内容。
    支持按城市强制地区过滤（香港→香港版Bing，东京→日本版Bing）。
    返回标准格式: [{title, url, snippet, score, source}, ...]
    """
    browser_tools = _has_browser_tool()
    if not browser_tools["has_playwright"]:
        return []  # Playwright Python 库未安装

    from urllib.parse import quote
    results = []

    # 根据城市强制 Bing 地区参数，避免内地结果垄断
    bing_region_params = ""
    if city == "香港":
        # setmkt=zh-HK = 香港市场, setlang=zh-Hant = 繁体中文
        bing_region_params = "&setmkt=zh-HK&setlang=zh-Hant"
    elif city == "东京":
        bing_region_params = "&setmkt=ja-JP&setlang=ja"
    elif city == "首尔":
        bing_region_params = "&setmkt=ko-KR&setlang=ko"
    elif city == "曼谷":
        bing_region_params = "&setmkt=th-TH&setlang=th"

    search_url = f"https://www.bing.com/search?q={quote(query)}&count={max_results * 2}{bing_region_params}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            # 根据城市设置 locale，让 Bing 知道我们要哪里的内容
            locale="zh-HK" if city == "香港" else ("ja-JP" if city == "东京" else ("ko-KR" if city == "首尔" else ("th-TH" if city == "曼谷" else "zh-CN"))),
        )
        page = context.new_page()

        try:
            page.goto(search_url, wait_until="networkidle", timeout=20000)
            page.wait_for_selector("li.b_algo", timeout=10000)

            # 提取搜索结果
            algo_elements = page.query_selector_all("li.b_algo")
            for li in algo_elements[:max_results * 2]:
                # 标题和链接
                h2_a = li.query_selector("h2 a")
                if not h2_a:
                    continue
                title = h2_a.inner_text().strip()
                href = h2_a.get_attribute("href") or ""

                # 过滤无意义标题
                if len(title) < 3 or title.lower() in ["zhihu.com", "baidu.com", "google.com"]:
                    continue
                if not href.startswith("http"):
                    continue

                # 摘要
                snippet_elem = li.query_selector("p")
                snippet = ""
                if snippet_elem:
                    snippet = snippet_elem.inner_text().strip()

                results.append({
                    "title": title,
                    "url": href,
                    "snippet": snippet,
                    "score": 0.5,
                    "source": "browser_search",
                })

                if len(results) >= max_results:
                    break

        except Exception:
            pass  # 超时或渲染失败，返回已收集的结果
        finally:
            browser.close()

    return results


def _search_static(query: str, max_results: int = 8, platform: str = None, city: str = None) -> list:
    """
    静态爬虫：尝试用 requests + BeautifulSoup 抓取 Bing 搜索结果。
    策略：能爬的优先爬（快），拿不到再 fallback。
    返回标准格式: [{title, url, snippet, score, source}, ...]
    
    如果传了 platform，会按目标平台域名过滤结果，减少无关内容混入。
    如果传了 city，会强制 Bing 地区参数，避免内地结果垄断。
    超时 15s 未返回则视为搜索失败，返回空列表。
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return []  # 依赖缺失，graceful fallback

    # 根据城市调整 Accept-Language，让 Bing 返回对应地区内容
    accept_lang = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7"
    if city == "香港":
        accept_lang = "zh-HK,zh-Hant;q=0.9,en-HK;q=0.8,en;q=0.7"
    elif city == "东京":
        accept_lang = "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7"
    elif city == "首尔":
        accept_lang = "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
    elif city == "曼谷":
        accept_lang = "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": accept_lang,
        "Referer": "https://www.bing.com/",
    }

    # 根据城市强制 Bing 地区参数
    bing_region_params = ""
    if city == "香港":
        bing_region_params = "&setmkt=zh-HK&setlang=zh-Hant"
    elif city == "东京":
        bing_region_params = "&setmkt=ja-JP&setlang=ja"
    elif city == "首尔":
        bing_region_params = "&setmkt=ko-KR&setlang=ko"
    elif city == "曼谷":
        bing_region_params = "&setmkt=th-TH&setlang=th"

    # 用 Bing 搜索（反爬比 Google 宽松，结果结构稳定）
    bing_url = f"https://www.bing.com/search?q={requests.utils.quote(query)}&count={max_results * 3}{bing_region_params}"

    # 重试 2 次，每次超时 15s
    resp = None
    for attempt in range(2):
        try:
            resp = requests.get(bing_url, headers=headers, timeout=15)
            resp.raise_for_status()
            break
        except requests.exceptions.Timeout:
            if attempt == 0:
                continue  # 重试一次
            return []  # 两次都超时，返回空
        except Exception:
            return []  # 其他网络异常，直接 fallback

    if resp is None:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    target_domains = PLATFORM_DOMAINS.get(platform, []) if platform else []

    # Bing 搜索结果结构：li.b_algo，标题在 h2 > a 中
    for li in soup.select("li.b_algo"):
        h2_a = li.select_one("h2 a")
        if h2_a:
            a = h2_a
        else:
            a = li.select_one("a")
        if not a:
            continue
        href = a.get("href", "")
        if not href.startswith("http"):
            continue

        title = a.get_text(strip=True)
        # 过滤掉无意义标题（纯域名、过短）
        if len(title) < 3 or title.lower() in ["zhihu.com", "baidu.com", "google.com"]:
            continue

        snippet_elem = li.select_one("p")
        if not snippet_elem:
            snippet_elem = li.select_one("[class*='caption']")
        snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

        # 如果指定了目标平台，按域名过滤
        if target_domains:
            domain = extract_domain(href)
            is_target = any(d in domain for d in target_domains)
            is_trusted = any(d in domain for d in TRUSTED_DOMAINS)
            if not (is_target or is_trusted):
                continue

        results.append({
            "title": title,
            "url": href,
            "snippet": snippet,
            "score": 0.5,
            "source": "static_crawl",
        })

        if len(results) >= max_results:
            break

    return results


def _search_from_cache(query: str, max_results: int = 8) -> list:
    """从 Agent 预写的搜索缓存中读取结果。"""
    cache_dir = SKILL_DIR / ".search_cache"
    if cache_dir.exists():
        cache_file = cache_dir / f"{hash(query) % 10000}.json"
        if cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                return cached.get("results", [])[:max_results]
            except Exception:
                pass
    return []


def search_web(query: str, max_results: int = 8, platform: str = None, city: str = None) -> list:
    """
    搜索入口：优先浏览器搜索（稳定），无浏览器时回退静态爬虫。
    返回统一格式: [{title, url, snippet, score, source}, ...]

    platform: 明确指定当前搜索的目标平台，用于域名过滤。
    city: 明确指定当前城市，用于强制 Bing 地区参数（解决内地结果垄断问题）。
    """
    results = []

    # === 第 1 层：浏览器搜索（优先，更稳定）===
    browser_results = _search_browser(query, max_results, city=city)
    if browser_results:
        results.extend(browser_results)

    # === 第 2 层：静态爬虫（浏览器不可用时回退）===
    if not results:
        static_results = _search_static(query, max_results, platform=platform, city=city)
        if static_results:
            results.extend(static_results)

    # === 第 3 层：Agent 缓存补充 ===
    if not results:
        cache_results = _search_from_cache(query, max_results)
        results.extend(cache_results)

    # 返回前裁剪到 max_results
    return results[:max_results]


def call_llm(system_prompt: str, user_message: str, model: str = "gpt-4o-mini") -> str:
    """
    调用 LLM。由 OpenClaw Agent 执行。
    
    注意：此函数在独立运行时不生效，需在 OpenClaw 环境中由 Agent 调用 LLM。
    返回占位符，提示调用方需要 Agent 介入。
    """
    # 将 prompt 写入 .llm_tasks/ 目录，由 Agent 读取并执行
    task_dir = SKILL_DIR / ".llm_tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    import time
    task_id = f"{int(time.time() * 1000)}"
    task_file = task_dir / f"{task_id}.json"
    task_data = {
        "id": task_id,
        "system_prompt": system_prompt,
        "user_message": user_message,
        "model": model,
        "status": "pending",
    }
    task_file.write_text(json.dumps(task_data, ensure_ascii=False), encoding="utf-8")
    return f"[AGENT_LLM_TASK:{task_id}] 需要由 OpenClaw Agent 执行此 LLM 任务。任务已写入 {task_file}"


def extract_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def contains_city_conflict(text: str, city_name: str) -> bool:
    city_markers = ["香港", "东京", "首尔", "曼谷", "深圳", "广州", "长沙", "青岛", "北京", "上海", "伦敦"]
    text = text or ""
    for marker in city_markers:
        if marker != city_name and marker in text:
            return True
    return False


def is_chain_like(name: str) -> bool:
    short_name = len(name.strip()) <= 4
    ascii_like = bool(re.search(r"[A-Za-z]", name))
    return short_name or ascii_like


def detect_marketing_noise(title: str, snippet: str, domain: str) -> dict:
    """
    检测搜索结果中的营销噪音程度。
    返回: {
        "is_heavy_marketing": bool,  # 重度营销（应直接丢弃）
        "marketing_score": int,       # 营销密度得分（越高越像广告）
        "signals": list[str],         # 命中的营销信号
        "trusted_source": bool,       # 是否来自可信域名
    }
    """
    title = title or ""
    snippet = snippet or ""
    combined = f"{title} {snippet}"
    signals = []
    marketing_score = 0

    # 1. 域名白名单检查 — 可信平台降权但不直接丢弃
    trusted = any(t in domain for t in TRUSTED_DOMAINS)

    # 2. 域名黑名单检查 — 直接标记为不可信
    if any(b in domain for b in BAD_DOMAINS):
        return {"is_heavy_marketing": True, "marketing_score": 10, "signals": ["不可信域名来源"], "trusted_source": False}

    # 3. 标题级营销词检测
    for word in MARKETING_BUZZWORDS:
        if word in title:
            signals.append(f"标题含「{word}」")
            marketing_score += 3  # 标题出现权重高

    # 4. Snippet 级营销词检测（用短列表减少误伤）
    snippet_marketing_count = 0
    for word in MARKETING_SNIPPET_SHORT:
        if word in snippet:
            snippet_marketing_count += 1
            signals.append(f"摘要含「{word}」")
    marketing_score += snippet_marketing_count * 1.5

    # 5. 营销密度判断：短时间内大量模板化表达
    template_patterns = [
        r"真的.*绝", r"绝.*绝", r"不去.*后悔",
        r"必吃.*必点", r"每次来.*必",
    ]
    for pat in template_patterns:
        if re.search(pat, combined):
            signals.append("模板化种草句式")
            marketing_score += 2

    # 6. 全大写 / 多感叹号（标题党特征）
    exclamation_count = title.count("!") + title.count("!") + title.count("～") + title.count("~")
    if exclamation_count >= 2:
        signals.append(f"标题含{exclamation_count}个感叹/波浪号")
        marketing_score += 2

    # 7. 纯体验无实质内容（全是情绪没有信息）
    no_info_keywords = ["好吃", "好吃!", "推荐", "不错", "很棒", "赞"]
    info_less_count = sum(1 for k in no_info_keywords if k in snippet)
    total_snippet_len = len(snippet.strip())
    if total_snippet_len > 0 and info_less_count >= 3 and total_snippet_len < 80:
        signals.append("短snippet全为泛泛夸赞")
        marketing_score += 2

    # 判定阈值
    is_heavy = (marketing_score >= 6) and (not trusted)
    # 即使可信域名，营销分过高也要标记
    if marketing_score >= 8:
        is_heavy = True

    return {
        "is_heavy_marketing": is_heavy,
        "marketing_score": round(marketing_score, 1),
        "signals": signals[:5],  # 最多保留5条信号
        "trusted_source": trusted,
    }


def resolve_restaurant_target(restaurant_name: str, city_name: str) -> dict:
    target = {
        "input_name": restaurant_name,
        "city": city_name,
        "brand_name": restaurant_name,
        "resolved_name": f"{restaurant_name} {city_name}",
        "branch_candidates": [],
        "is_chain_like": is_chain_like(restaurant_name),
        "confidence": "low",
        "notes": "未发现明显分店线索",
    }

    discovery_queries = [
        f"{restaurant_name} {city_name} 官网 分店",
        f"{restaurant_name} {city_name} 地址",
    ]

    branch_hits = []
    for query in discovery_queries:
        try:
            results = search_web(query, max_results=6, city=city_name)
        except Exception:
            continue
        for item in results:
            text = f"{item.get('title', '')}\n{item.get('snippet', '')}"
            if restaurant_name not in text:
                continue
            if city_name in text:
                branch_hits.append(item)

    branch_names = []
    for item in branch_hits:
        text = f"{item.get('title', '')} {item.get('snippet', '')}"
        for hint in CHAIN_HINTS:
            if hint in text.lower() or hint in text:
                branch_names.append(hint)

    dedup = []
    for x in branch_names:
        if x not in dedup:
            dedup.append(x)

    if dedup:
        target["branch_candidates"] = dedup[:4]
        target["confidence"] = "medium"
        target["notes"] = "检测到可能存在多分店/品牌输入，后续搜索会优先带分店锚点"
    elif target["is_chain_like"]:
        target["confidence"] = "medium"
        target["notes"] = "名称较短或偏品牌名，需警惕品牌资料与单店评价混淆"
    else:
        target["confidence"] = "high"
        target["notes"] = "看起来更像单店名，可直接围绕目标门店搜索"

    return target


def platform_queries(target: dict) -> dict:
    restaurant_name = target["brand_name"]
    city_name = target["city"]
    branch_candidates = target.get("branch_candidates", [])

    anchor = branch_candidates[0] if branch_candidates else city_name

    queries = {
        "google_maps": [
            f'{restaurant_name} {city_name} Google Maps',
            f'site:google.com/maps "{restaurant_name}" "{anchor}"',
        ],
        "dianping": [
            f'{restaurant_name} {city_name} 大众点评',
            f'site:dianping.com "{restaurant_name}" "{anchor}"',
        ],
        "xiaohongshu": [
            f'{restaurant_name} {city_name} 小红书',
            f'site:xiaohongshu.com "{restaurant_name}" "{anchor}"',
        ],
    }

    if city_name == "香港":
        queries["openrice"] = [
            f'{restaurant_name} 香港 OpenRice',
            f'site:openrice.com "{restaurant_name}" "{anchor}" 香港',
        ]

    return queries


def score_result(item: dict, target: dict, platform: str) -> float:
    title = item.get("title", "")
    snippet = item.get("snippet", "")
    url = item.get("url", "")
    domain = extract_domain(url)
    text = f"{title}\n{snippet}"
    score = float(item.get("score", 0))

    restaurant_name = target["brand_name"]
    city_name = target["city"]
    branch_candidates = target.get("branch_candidates", [])

    # ===== 加分项 =====
    if restaurant_name in title or restaurant_name in snippet:
        score += 3
    if city_name in title or city_name in snippet or city_name in url:
        score += 2
    # 平台权重：OpenRice 最高（香港本地最可信），TripAdvisor 最低（游客偏差大）
    platform_weights = {
        "openrice": 6,
        "google_maps": 5,
        "dianping": 4,
        "xiaohongshu": 3,
        "tripadvisor": 2,
    }
    if any(d in domain for d in PLATFORM_DOMAINS.get(platform, [])):
        score += platform_weights.get(platform, 3)
    if branch_candidates:
        if any(branch.lower() in text.lower() for branch in branch_candidates):
            score += 2

    # ===== 扣分项 =====

    # 1. 城市冲突（提到别的城市）
    if contains_city_conflict(text, city_name):
        score -= 4

    # 2. 标题级垃圾词（聚合页/列表页）
    if any(bad in title for bad in BAD_TITLE_HINTS):
        score -= 3  # 从 -2 提高到 -3，更严格

    # 3. Snippet 级垃圾词（轻量版）
    if any(bad in snippet for bad in BAD_TITLE_HINTS[:6]):
        score -= 1

    # 4. 目标店名完全不在文本中
    if restaurant_name not in text:
        score -= 2

    # 5. ★ 营销噪音检测（核心新增）
    marketing = detect_marketing_noise(title, snippet, domain)
    item["_marketing_info"] = marketing  # 挂载到 item 上供后续展示

    if marketing["is_heavy_marketing"]:
        score -= 8  # 重度营销直接大额扣分
    elif marketing["marketing_score"] >= 4:
        score -= 3  # 中度营销扣分
    elif marketing["marketing_score"] >= 2:
        score -= 1  # 轻度营销轻微扣分

    return score


def filter_platform_results(results: list, target: dict, platform: str) -> list:
    rescored = []
    for item in results:
        item = dict(item)
        item["quality_score"] = score_result(item, target, platform)
        # 营销噪音直接过滤：重度营销且非可信来源的直接丢弃
        marketing = item.get("_marketing_info", {})
        if marketing.get("is_heavy_marketing") and not marketing.get("trusted_source"):
            continue  # 直接跳过，不进入候选
        rescored.append(item)
    rescored.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
    return [r for r in rescored if r.get("quality_score", 0) > 0][:3]


def summarize_platform_result(platform: str, query_used: str, results: list) -> dict:
    matched = len(results) > 0
    top = results[0] if matched else None
    strength = "low"
    if matched and top.get("quality_score", 0) >= 8:
        strength = "high"
    elif matched and top.get("quality_score", 0) >= 4:
        strength = "medium"

    return {
        "platform": platform,
        "query_used": query_used,
        "matched": matched,
        "signal_strength": strength,
        "top_result": top,
        "results": results,
    }


def format_result_line(item: dict) -> str:
    title = item.get("title", "") or "无标题"
    url = item.get("url", "") or "无链接"
    snippet = (item.get("snippet", "") or "").replace("\n", " ").strip()
    snippet = snippet[:160] + ("..." if len(snippet) > 160 else "")
    quality = item.get("quality_score", 0)

    # 营销标签
    marketing = item.get("_marketing_info", {})
    tag = ""
    if marketing.get("marketing_score", 0) >= 4:
        tag = " ⚠️ 可能含营销内容"
    elif marketing.get("marketing_score", 0) >= 2:
        tag = " 🟡 轻度营销味"

    return f"- {title}\n  URL: {url}\n  摘要: {snippet}\n  命中质量: {quality:.1f}{tag}"


def collect_search_bundle(target: dict) -> dict:
    queries = platform_queries(target)
    bundle = {
        "target": target,
        "platforms": {},
    }

    city_name = target.get("city", "")
    for platform, query_list in queries.items():
        best_summary = None
        for query in query_list:
            raw_results = search_web(query, platform=platform, city=city_name)
            filtered = filter_platform_results(raw_results, target, platform)
            summary = summarize_platform_result(platform, query, filtered)
            if not best_summary or summary["signal_strength"] > best_summary["signal_strength"]:
                best_summary = summary
            if summary["signal_strength"] == "high":
                break
        bundle["platforms"][platform] = best_summary or summarize_platform_result(platform, query_list[0], [])
    return bundle


def format_search_bundle(bundle: dict) -> str:
    target = bundle["target"]
    strong = []
    weak = []
    lines = [
        "## 目标门店定位",
        f"- 用户输入：{target['input_name']}",
        f"- 城市：{target['city']}",
        f"- 判定：{'品牌/连锁型输入' if target['is_chain_like'] else '更像单店输入'}",
        f"- 疑似分店锚点：{', '.join(target.get('branch_candidates', [])) if target.get('branch_candidates') else '未识别到'}",
        f"- 定位置信度：{target['confidence']}",
        f"- 说明：{target['notes']}",
        "",
        "## 检索概览",
    ]
    for platform, summary in bundle.get("platforms", {}).items():
        name = PLATFORM_DISPLAY_NAMES.get(platform, platform)
        if summary.get("signal_strength") in ["high", "medium"]:
            strong.append(name)
        else:
            weak.append(name)

    lines.append(f"- 高命中平台：{', '.join(strong) if strong else '无'}")
    lines.append(f"- 弱命中/无命中平台：{', '.join(weak) if weak else '无'}")

    for platform, summary in bundle.get("platforms", {}).items():
        name = PLATFORM_DISPLAY_NAMES.get(platform, platform)

        lines.append(f"\n### {name}")
        lines.append(f"查询：{summary.get('query_used', '')}")
        lines.append(f"命中强度：{summary.get('signal_strength', 'low')}")

        if not summary.get("matched"):
            # 判断是搜索失败还是未命中
            results = summary.get("results", [])
            if not results:
                lines.append("- 搜索失败或超时，未获取到数据")
            else:
                lines.append("- 未命中目标门店结果")
            continue
        for item in summary.get("results", [])[:2]:
            lines.append(format_result_line(item))

    return "\n".join(lines)


def generate_expert_analysis(search_bundle: dict, target: dict, concern: str = "") -> dict:
    """
    基于搜索结果，为每个专家 Agent 生成结构化的分析摘要。
    Native 模式下没有 LLM，我们用规则引擎模拟各专家的视角。
    返回: {expert_key: analysis_text}
    """
    platforms = search_bundle.get("platforms", {})
    city = target.get("city", "")
    restaurant = target.get("brand_name", "")

    # ===== 1. 线索猎犬：平台证据汇总 =====
    platform_scores = {}
    platform_reviews = {}
    for pkey, summary in platforms.items():
        if summary and summary.get("matched"):
            top = summary.get("top_result", {})
            platform_scores[pkey] = top.get("quality_score", 0)
            platform_reviews[pkey] = summary.get("results", [])

    search_lines = [f"目标：{restaurant}（{city}）"]
    search_lines.append(f"输入类型：{'品牌/连锁型' if target.get('is_chain_like') else '单店型'}")
    if target.get("branch_candidates"):
        search_lines.append(f"分店线索：{', '.join(target['branch_candidates'])}")

    for pkey, summary in platforms.items():
        name = PLATFORM_DISPLAY_NAMES.get(pkey, pkey)
        if summary and summary.get("matched"):
            strength = summary.get("signal_strength", "low")
            top = summary.get("top_result", {})
            snippet = (top.get("snippet", "") or "")[:80]
            search_lines.append(f"- {name}：信号强度 {strength} | 质量分 {top.get('quality_score', 0):.1f} | {snippet}...")
        else:
            search_lines.append(f"- {name}：未命中高质量结果")

    expert_search = "\n".join(search_lines)

    # ===== 2. 拆台师：跨平台矛盾检测 =====
    contradictions = []
    scores = {}
    for pkey, summary in platforms.items():
        if summary and summary.get("matched"):
            scores[pkey] = summary.get("signal_strength", "low")

    # 评分不一致
    strengths = list(scores.values())
    if strengths:
        high_count = sum(1 for s in strengths if s == "high")
        low_count = sum(1 for s in strengths if s == "low")
        if high_count > 0 and low_count > 0:
            contradictions.append("不同平台信号强度差异明显：部分平台高命中，部分平台几乎无信号")

    # 小红书 vs 其他平台
    xhs = platforms.get("xiaohongshu")
    others = [platforms.get(k) for k in ["google_maps", "openrice", "dianping"] if platforms.get(k)]
    if xhs and xhs.get("matched"):
        xhs_marketing = False
        for item in xhs.get("results", []):
            m = item.get("_marketing_info", {})
            if m.get("marketing_score", 0) >= 2:
                xhs_marketing = True
                break
        if xhs_marketing and any(o and o.get("matched") for o in others):
            contradictions.append("小红书内容营销味明显，与其他平台的客观评分形成反差")

    # 多分店问题
    if target.get("branch_candidates"):
        contradictions.append(f"检测到多分店/连锁（{', '.join(target['branch_candidates'][:3])}），不同分店体验可能不一致")

    if not contradictions:
        contradictions.append("未发现明显跨平台矛盾，各平台信号方向基本一致")

    expert_marketing = "\n".join([f"- {c}" for c in contradictions])

    # ===== 3. 评论法医：评论质量分析 =====
    review_quality = []
    total_reviews = 0
    marketing_items = 0
    for pkey, summary in platforms.items():
        if summary:
            for item in summary.get("results", []):
                total_reviews += 1
                m = item.get("_marketing_info", {})
                if m.get("marketing_score", 0) >= 2:
                    marketing_items += 1

    if total_reviews > 0:
        marketing_ratio = marketing_items / total_reviews
        if marketing_ratio > 0.5:
            review_quality.append(f"营销内容占比高（{marketing_ratio:.0%}），评论可信度存疑")
        elif marketing_ratio > 0.2:
            review_quality.append(f"部分结果含营销信号（{marketing_ratio:.0%}），需交叉验证")
        else:
            review_quality.append("营销噪音比例低，评论整体可信度较高")

    # OpenRice 评论
    or_summary = platforms.get("openrice")
    if or_summary and or_summary.get("matched"):
        review_quality.append("OpenRice 有本地用户评分，评论通常包含具体菜品描述，可信度较高")
    else:
        review_quality.append("OpenRice 未命中或信号弱，缺少香港本地食客视角")

    # TripAdvisor 评论
    ta_summary = platforms.get("tripadvisor")
    if ta_summary and ta_summary.get("matched"):
        review_quality.append("TripAdvisor 以游客评价为主，可能存在'旅行滤镜'，参考价值有限")

    expert_review = "\n".join([f"- {r}" for r in review_quality]) if review_quality else "- 评论样本不足，无法判断质量"

    # ===== 4. 街坊雷达：本地认可度 =====
    local_signals = []
    has_openrice = platforms.get("openrice") and platforms.get("openrice").get("matched")
    has_dianping = platforms.get("dianping") and platforms.get("dianping").get("matched")
    has_xhs = platforms.get("xiaohongshu") and platforms.get("xiaohongshu").get("matched")
    has_ta = platforms.get("tripadvisor") and platforms.get("tripadvisor").get("matched")

    if has_openrice:
        local_signals.append("OpenRice 有信号 → 香港本地食客有讨论")
    else:
        local_signals.append("OpenRice 无信号 → 本地食客讨论度低")

    if has_dianping:
        local_signals.append("大众点评有信号 → 内地游客有关注")

    if has_xhs and not has_openrice:
        local_signals.append("小红书热度高但 OpenRice 信号弱 → 更可能是'游客热'而非'本地认可'")
    elif has_xhs and has_openrice:
        local_signals.append("小红书 + OpenRice 双平台有信号 → 游客和本地都有一定认可")

    if has_ta and not has_openrice:
        local_signals.append("TripAdvisor 有信号但 OpenRice 弱 → 纯游客店特征明显")

    if target.get("is_chain_like"):
        local_signals.append("品牌/连锁型 → 标准化出品，但可能缺乏单店特色")

    expert_local = "\n".join([f"- {s}" for s in local_signals]) if local_signals else "- 本地认可度信号不足"

    # ===== 5. 场景裁剪师：适配性判断 =====
    scene_lines = []
    scene_lines.append(f"用户担心点：{concern or '未特别说明，默认担心踩雷'}")

    # 基于平台信号判断"值不值得专门去"
    high_signal_platforms = [k for k, s in platforms.items() if s and s.get("signal_strength") == "high"]
    if len(high_signal_platforms) >= 2:
        scene_lines.append("多平台高命中 → 有一定真实口碑支撑，顺路值得尝试")
    elif len(high_signal_platforms) == 1:
        scene_lines.append("仅单平台高命中 → 口碑基础薄弱，不建议专门跑一趟")
    else:
        scene_lines.append("无平台高命中 → 证据不足，建议降低预期或换一家")

    # 连锁/分店判断
    if target.get("branch_candidates"):
        scene_lines.append(f"多分店连锁（{len(target['branch_candidates'])}个区域有店）→ 不需要专门去某一家，选最方便的即可")

    # 价格暗示
    or_summary = platforms.get("openrice")
    if or_summary and or_summary.get("matched"):
        top = or_summary.get("top_result", {})
        snippet = top.get("snippet", "")
        if "$" in snippet or "港币" in snippet or "元" in snippet:
            scene_lines.append("OpenRice 有价格信息 → 可提前判断预算是否匹配")

    # 营销热度 vs 实际口碑
    xhs = platforms.get("xiaohongshu")
    if xhs and xhs.get("matched"):
        marketing_count = 0
        for item in xhs.get("results", []):
            m = item.get("_marketing_info", {})
            if m.get("marketing_score", 0) >= 2:
                marketing_count += 1
        if marketing_count > 0:
            scene_lines.append("小红书营销信号明显 → 实际体验可能低于预期，建议去滤镜")

    expert_scene = "\n".join([f"- {s}" for s in scene_lines])

    # ===== 6. 收口官：综合裁决 =====
    # 计算加权综合分
    weighted_score = 0
    total_weight = 0
    platform_weights_judge = {
        "openrice": 0.30,
        "google_maps": 0.25,
        "dianping": 0.20,
        "xiaohongshu": 0.15,
        "tripadvisor": 0.10,
    }
    for pkey, summary in platforms.items():
        if summary and summary.get("matched"):
            weight = platform_weights_judge.get(pkey, 0.15)
            strength_map = {"high": 1.0, "medium": 0.6, "low": 0.2}
            signal_val = strength_map.get(summary.get("signal_strength", "low"), 0.2)
            weighted_score += signal_val * weight
            total_weight += weight

    if total_weight > 0:
        final_score = weighted_score / total_weight
    else:
        final_score = 0

    # 营销惩罚
    marketing_penalty = 0
    for pkey, summary in platforms.items():
        if summary:
            for item in summary.get("results", []):
                m = item.get("_marketing_info", {})
                if m.get("is_heavy_marketing"):
                    marketing_penalty += 0.15
                elif m.get("marketing_score", 0) >= 4:
                    marketing_penalty += 0.08
    final_score = max(0, final_score - marketing_penalty)

    # 判定
    if final_score >= 0.7:
        verdict = "值得去"
        risk = "低"
        confidence = "高" if total_weight >= 0.6 else "中"
    elif final_score >= 0.4:
        verdict = "谨慎去"
        risk = "中"
        confidence = "中"
    else:
        verdict = "不建议"
        risk = "高"
        confidence = "低" if total_weight < 0.4 else "中"

    # 风险标签
    risk_tags = []
    if platforms.get("xiaohongshu") and platforms.get("xiaohongshu").get("matched"):
        xhs_items = platforms["xiaohongshu"].get("results", [])
        m_count = sum(1 for i in xhs_items if i.get("_marketing_info", {}).get("marketing_score", 0) >= 2)
        if m_count > 0:
            risk_tags.append("网红过热")
    if target.get("is_chain_like"):
        risk_tags.append("连锁标准化")
    if not (platforms.get("openrice") and platforms.get("openrice").get("matched")):
        risk_tags.append("本地认可度不明")
    if target.get("branch_candidates"):
        risk_tags.append("多分店体验差异")

    judge_lines = [
        f"综合评分：{final_score:.2f}/1.00（OpenRice 权重最高，TripAdvisor 权重最低）",
        f"裁决：{verdict}",
        f"踩雷风险：{risk}",
        f"置信度：{confidence}",
        f"风险标签：{', '.join(risk_tags) if risk_tags else '无明显风险标签'}",
    ]

    # 适合谁 / 不适合谁
    if verdict == "值得去":
        judge_lines.append("适合：想尝试这家店的人，口碑有真实支撑")
        judge_lines.append("不太适合：对这家店完全没兴趣的人")
    elif verdict == "谨慎去":
        judge_lines.append("适合：住附近/顺路的人、愿意尝试的人")
        judge_lines.append("不太适合：专门跑一趟、时间紧、预算敏感的人")
    else:
        judge_lines.append("适合：几乎没人")
        judge_lines.append("不太适合：认真找好吃的、不想失望的人")

    # 一句话建议
    if final_score >= 0.7:
        advice = f"{restaurant} 口碑有真实支撑，如果你在附近或顺路，值得一试。"
    elif final_score >= 0.4:
        advice = f"{restaurant} 有亮点也有风险，建议降低预期、顺路尝试，不要专门安排行程。"
    else:
        advice = f"{restaurant} 证据不足或口碑偏差较大，建议换一家更稳妥的选择。"
    judge_lines.append(f"一句话建议：{advice}")

    expert_judge = "\n".join([f"- {l}" for l in judge_lines])

    return {
        "search": expert_search,
        "marketing": expert_marketing,
        "review": expert_review,
        "local": expert_local,
        "scene": expert_scene,
        "judge": expert_judge,
    }


def load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt 文件不存在: {path}")
    return path.read_text(encoding="utf-8")


def detect_city(user_input: str):
    user_input_lower = user_input.lower()
    for city_name, city_id in CITIES.items():
        if city_name.lower() in user_input_lower:
            return city_name, city_id
    return None, None


class FoodBuddyMVP:
    def __init__(self):
        self.city_name = None
        self.city_id = None
        self.expert_outputs = {}
        self._browser_warned = False

    def _check_browser(self):
        """检测浏览器搜索能力，未安装时给出一次性提示。"""
        if self._browser_warned:
            return
        tools = _has_browser_tool()
        if not tools["any"]:
            print("\n⚠️  提示：未检测到浏览器自动化工具。")
            print("    搜索将回退到静态爬虫模式，部分平台（如 OpenRice、小红书）可能无法获取数据。")
            print("    如需完整体验，请安装以下任一浏览器 skill：")
            print("      • playwright-browser-automation  →  pip install playwright && playwright install chromium")
            print("      • browser-use                    → curl -fsSL https://browser-use.com/cli/install.sh | bash")
            print("      • clawbrowser                    → npm install -g @playwright/cli@latest")
            print("      • stagehand-browser-cli          → npm install && npm link")
            print()
            self._browser_warned = True

    def set_city(self, city_input: str):
        city_name, city_id = detect_city(city_input)
        if not city_id:
            raise ValueError(f"不支持的城市: {city_input}")
        self.city_name = city_name
        self.city_id = city_id
        return city_name

    def run_verification(self, restaurant_name: str, concern: str = "") -> dict:
        if not self.city_name:
            raise ValueError("请先设置城市")

        base_input = f"城市：{self.city_name}\n目标餐厅：{restaurant_name}\n用户担心点：{concern or '未特别说明，默认担心踩雷'}"

        self._check_browser()

        print("\n🧭 正在定位目标门店...")
        target = resolve_restaurant_target(restaurant_name, self.city_name)

        print("\n🌐 正在执行真实搜索（含营销噪音过滤）...")
        search_bundle = collect_search_bundle(target)
        search_context = format_search_bundle(search_bundle)

        print("\n🧠 正在生成多专家分析...")
        expert_outputs = generate_expert_analysis(search_bundle, target, concern)
        self.expert_outputs = expert_outputs

        return {
            "base_input": base_input,
            "target": target,
            "search_context": search_context,
            "search_bundle": search_bundle,
            "expert_outputs": expert_outputs,
        }

    def format_report(self) -> str:
        if not self.expert_outputs:
            return ""

        sections = [
            ("search", "🔍 线索猎犬"),
            ("marketing", "🔥 拆台师"),
            ("review", "📝 评论法医"),
            ("local", "🏠 街坊雷达"),
            ("scene", "🎭 场景裁剪师"),
            ("judge", "⚖️ 收口官"),
        ]

        output = "\n" + "=" * 50 + "\n"
        output += "餐厅防踩雷验证过程\n"
        output += "=" * 50 + "\n\n"

        for key, title in sections:
            if key in self.expert_outputs:
                output += f"### {title}\n\n{self.expert_outputs[key]}\n\n"
        return output


def interactive_mode():
    print("=" * 60)
    print("🍽️ 食通天 FoodBuddy — 餐厅防踩雷验证工具")
    print("=" * 60)
    print("\n由 OpenClaw Agent 驱动，使用内置搜索与 LLM 能力。\n")

    mvp = FoodBuddyMVP()

    print("先输入城市，再输入你想验证的餐厅。")
    print("示例：香港 → 正斗，我想知道值不值得专门去\n")

    waiting_for_restaurant = False

    while True:
        try:
            user_input = input("\n你: ").strip()
            if not user_input:
                continue

            if user_input.lower() in ["exit", "退出", "bye", "再见"]:
                print("\n下次见，愿你少踩雷。")
                break

            if not mvp.city_name:
                city_name, city_id = detect_city(user_input)
                if city_id:
                    mvp.set_city(user_input)
                    waiting_for_restaurant = True
                    print(f"\n📍 已设置城市：{city_name}")
                    print("请输入你想验证的餐厅名，或者加一句你担心什么。")
                else:
                    print("\n请先输入支持的城市，例如：香港、东京、曼谷、首尔")
                continue

            if waiting_for_restaurant:
                restaurant_name = user_input
                concern = ""
                if "，" in user_input or "," in user_input:
                    parts = re.split(r"[，,]", user_input, maxsplit=1)
                    restaurant_name = parts[0].strip()
                    concern = parts[1].strip() if len(parts) > 1 else ""

                result = mvp.run_verification(restaurant_name, concern)

                # 展示搜索过滤结果
                print(f"\n{'='*60}")
                print("🔎 搜索与过滤结果（已过滤营销噪音）")
                print(f"{'='*60}\n")
                print(result["search_context"])

                # 展示各专家分析（规则引擎生成）
                expert_outputs = result.get("expert_outputs", {})
                if expert_outputs:
                    print(f"\n{'='*60}")
                    print("🧠 多专家分析")
                    print(f"{'='*60}")

                    expert_sections = [
                        ("search", "🔍 线索猎犬 — 平台证据汇总"),
                        ("marketing", "🔥 拆台师 — 跨平台矛盾检测"),
                        ("review", "📝 评论法医 — 评论质量分析"),
                        ("local", "🏠 街坊雷达 — 本地认可度判断"),
                        ("scene", "🎭 场景裁剪师 — 场景适配分析"),
                        ("judge", "⚖️ 收口官 — 综合裁决"),
                    ]
                    for key, title in expert_sections:
                        if key in expert_outputs:
                            print(f"\n### {title}\n{expert_outputs[key]}")

                print("\n你可以继续输入另一家店名继续验证，或输入 exit 退出。")

        except KeyboardInterrupt:
            print("\n\n下次见！")
            break
        except Exception as e:
            print(f"\n❌ 出错了：{e}")


if __name__ == "__main__":
    interactive_mode()
