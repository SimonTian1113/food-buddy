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
    # 港澳
    "香港": "hongkong",
    "Hong Kong": "hongkong",
    "hk": "hongkong",
    "澳门": "macau",
    "Macau": "macau",
    # 内地
    "北京": "beijing",
    "Beijing": "beijing",
    "上海": "shanghai",
    "Shanghai": "shanghai",
    "广州": "guangzhou",
    "Guangzhou": "guangzhou",
    "深圳": "shenzhen",
    "Shenzhen": "shenzhen",
    "成都": "chengdu",
    "Chengdu": "chengdu",
    "杭州": "hangzhou",
    "Hangzhou": "hangzhou",
    "长沙": "changsha",
    "Changsha": "changsha",
    "重庆": "chongqing",
    "Chongqing": "chongqing",
    "武汉": "wuhan",
    "Wuhan": "wuhan",
    "南京": "nanjing",
    "Nanjing": "nanjing",
    "西安": "xian",
    # 台湾
    "台北": "taipei",
    "Taipei": "taipei",
    # 海外
    "曼谷": "bangkok",
    "Bangkok": "bangkok",
    "bkk": "bangkok",
    "东京": "tokyo",
    "Tokyo": "tokyo",
    "首尔": "seoul",
    "Seoul": "seoul",
}

# ===== 区域分类：决定平台权重体系和搜索策略 =====
REGION_HK_MACAU = "hk_macau"   # 港澳模式
REGION_MAINLAND = "mainland"    # 内地模式
REGION_TAIWAN = "taiwan"        # 台湾模式
REGION_OVERSEAS = "overseas"    # 海外模式

CITY_REGIONS = {
    # 港澳
    "香港": REGION_HK_MACAU, "澳门": REGION_HK_MACAU,
    # 内地
    "北京": REGION_MAINLAND, "上海": REGION_MAINLAND, "广州": REGION_MAINLAND,
    "深圳": REGION_MAINLAND, "成都": REGION_MAINLAND, "杭州": REGION_MAINLAND,
    "长沙": REGION_MAINLAND, "重庆": REGION_MAINLAND, "武汉": REGION_MAINLAND,
    "南京": REGION_MAINLAND, "西安": REGION_MAINLAND,
    # 台湾
    "台北": REGION_TAIWAN,
    # 海外
    "曼谷": REGION_OVERSEAS, "东京": REGION_OVERSEAS, "首尔": REGION_OVERSEAS,
}

TAVILY_API_URL = "https://api.tavily.com/search"

# ===== 港澳模式平台配置 =====
PLATFORM_DISPLAY_NAMES = {
    "google_maps": "Google Maps",
    "dianping": "大众点评",
    "xiaohongshu": "小红书",
    "openrice": "OpenRice",
    "tripadvisor": "TripAdvisor",
}
PLATFORM_DOMAINS = {
    "google_maps": ["google.com", "maps.google.com"],
    "dianping": ["dianping.com", "m.dianping.com"],
    "xiaohongshu": ["xiaohongshu.com", "www.xiaohongshu.com"],
    "openrice": ["openrice.com"],
    "tripadvisor": ["tripadvisor.com", "tripadvisor.com.hk"],
}

# ===== 内地模式平台配置 =====
MAINLAND_PLATFORM_DISPLAY_NAMES = {
    "dianping": "大众点评",
    "douyin": "抖音",
    "xiaohongshu": "小红书",
    "gaode": "高德",
    "general": "综合",
}
MAINLAND_PLATFORM_DOMAINS = {
    "dianping": ["dianping.com", "m.dianping.com"],
    "douyin": ["douyin.com", "www.douyin.com", "iesdouyin.com"],
    "xiaohongshu": ["xiaohongshu.com", "www.xiaohongshu.com"],
    "gaode": ["amap.com", "gaode.com"],
    "general": [],  # 综合搜索无特定域名过滤
}

# ===== 区域 → 平台权重映射 =====
REGION_PLATFORM_WEIGHTS = {
    REGION_HK_MACAU: {
        "openrice": 0.30,
        "google_maps": 0.25,
        "dianping": 0.20,
        "xiaohongshu": 0.15,
        "tripadvisor": 0.10,
    },
    REGION_MAINLAND: {
        "dianping": 0.20,
        "douyin": 0.20,
        "xiaohongshu": 0.20,
        "gaode": 0.20,
        "general": 0.20,
    },
    REGION_TAIWAN: {
        "openrice": 0.30,
        "google_maps": 0.25,
        "dianping": 0.20,
        "xiaohongshu": 0.15,
        "tripadvisor": 0.10,
    },
    REGION_OVERSEAS: {
        "google_maps": 0.30,
        "tripadvisor": 0.25,
        "dianping": 0.20,
        "xiaohongshu": 0.15,
        "openrice": 0.10,
    },
}

# ===== 区域 → 平台显示名映射 =====
REGION_DISPLAY_NAMES = {
    REGION_HK_MACAU: PLATFORM_DISPLAY_NAMES,
    REGION_MAINLAND: MAINLAND_PLATFORM_DISPLAY_NAMES,
    REGION_TAIWAN: PLATFORM_DISPLAY_NAMES,
    REGION_OVERSEAS: PLATFORM_DISPLAY_NAMES,
}

# ===== 区域 → 平台域名映射 =====
REGION_DOMAINS = {
    REGION_HK_MACAU: PLATFORM_DOMAINS,
    REGION_MAINLAND: MAINLAND_PLATFORM_DOMAINS,
    REGION_TAIWAN: PLATFORM_DOMAINS,
    REGION_OVERSEAS: PLATFORM_DOMAINS,
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
    "douyin.com",                         # 抖音
    "amap.com", "gaode.com",              # 高德
    "yelp.com",                           # Yelp
    "weibo.com",                          # 微博
    "ctrip.com",                          # 携程
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
    强制使用 Bing HK 地区参数，确保搜索结果优先返回香港本地内容。
    返回标准格式: [{title, url, snippet, score, source}, ...]
    """
    browser_tools = _has_browser_tool()
    if not browser_tools["has_playwright"]:
        return []  # Playwright Python 库未安装

    from urllib.parse import quote
    results = []

    # Bing 地区参数：确保搜索本地内容
    bing_params = ""
    locale = "zh-CN"
    accept_lang = "zh-CN,zh;q=0.9,en;q=0.8"
    
    region = CITY_REGIONS.get(city, REGION_MAINLAND)
    
    if region == REGION_HK_MACAU:
        bing_params = "&setmkt=zh-HK&setlang=zh-Hant"
        locale = "zh-HK"
        accept_lang = "zh-HK,zh-Hant;q=0.9,en;q=0.8"
    elif region == REGION_TAIWAN:
        bing_params = "&setmkt=zh-TW&setlang=zh-TW"
        locale = "zh-TW"
        accept_lang = "zh-TW,zh;q=0.9,en;q=0.8"
    elif region == REGION_MAINLAND:
        bing_params = "&setmkt=zh-CN&setlang=zh-Hans"
        locale = "zh-CN"
        accept_lang = "zh-CN,zh;q=0.9,en;q=0.8"
    elif city == "东京":
        bing_params = "&setmkt=ja-JP&setlang=ja"
        locale = "ja-JP"
        accept_lang = "ja;q=0.9,en;q=0.8"
    elif city == "首尔":
        bing_params = "&setmkt=ko-KR&setlang=ko"
        locale = "ko-KR"
        accept_lang = "ko;q=0.9,en;q=0.8"
    elif city == "曼谷":
        bing_params = "&setmkt=th-TH&setlang=th"
        locale = "th-TH"
        accept_lang = "th;q=0.9,en;q=0.8"

    search_url = f"https://www.bing.com/search?q={quote(query)}&count={max_results * 2}{bing_params}"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale=locale,
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            extra_http_headers={"Accept-Language": accept_lang},
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


def _search_static(query: str, max_results: int = 8, platform: str = None) -> list:
    """
    静态爬虫：尝试用 requests + BeautifulSoup 抓取 Bing 搜索结果。
    策略：能爬的优先爬（快），拿不到再 fallback。
    返回标准格式: [{title, url, snippet, score, source}, ...]
    
    如果传了 platform，会按目标平台域名过滤结果，减少无关内容混入。
    超时 15s 未返回则视为搜索失败，返回空列表。
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return []  # 依赖缺失，graceful fallback

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.bing.com/",
    }

    # 用 Bing 搜索（反爬比 Google 宽松，结果结构稳定）
    bing_url = f"https://www.bing.com/search?q={requests.utils.quote(query)}&count={max_results * 3}"

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
    搜索入口：强制 Bing HK + Playwright，确保地区参数正确。
    返回统一格式: [{title, url, snippet, score, source}, ...]

    核心策略：Bing HK 强制搜索，不走大陆搜索引擎。
    - city 参数控制地区参数（setmkt/setlang）
    - 默认走 Playwright 浏览器搜索（能渲染 JS，获取更完整的 snippet）
    - 浏览器不可用时回退静态爬虫
    - 最后 fallback 到缓存
    """
    results = []

    # === 第 1 层：浏览器搜索（优先，更完整）===
    browser_results = _search_browser(query, max_results, city=city)
    if browser_results:
        results.extend(browser_results)

    # === 第 2 层：静态爬虫（浏览器不可用时回退）===
    if not results:
        static_results = _search_static(query, max_results, platform=platform, city=city)
        if static_results:
            results.extend(static_results)

    # === 第 3 层：缓存保底 ===
    if not results:
        cache_results = _search_from_cache(query, max_results)
        results.extend(cache_results)

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
            results = search_web(query, max_results=6)
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
    """
    搜索策略：根据区域自动切换平台搜索方案

    港澳模式：权威平台精准搜索（OpenRice/Google Maps/TripAdvisor/大众点评）+ 小红书热度
    内地模式：四大厂商平台（大众点评/抖音/小红书/高德）+ 综合搜索（新闻/旅游/微博）

    查询格式设计原则：
    - 平台名在前，确保 Bing 返回该平台的结果
    - 用引号包裹品牌名，避免模糊匹配
    - 加城市锚点，过滤掉其他地区的结果
    """
    restaurant_name = target["brand_name"]
    city_name = target["city"]
    branch_candidates = target.get("branch_candidates", [])
    anchor = branch_candidates[0] if branch_candidates else city_name

    region = CITY_REGIONS.get(city_name, REGION_MAINLAND)
    queries = {}

    if region == REGION_HK_MACAU:
        # ===== 港澳模式 =====
        # OpenRice 是港澳最权威的饮食平台
        queries["openrice"] = [
            f'site:openrice.com "{restaurant_name}" {anchor}',
            f'"{restaurant_name}" {anchor} openrice',
        ]
        queries["google_maps"] = [
            f'"{restaurant_name}" {anchor} site:google.com/maps',
            f'"{restaurant_name}" {anchor} Google Maps 评分',
        ]
        queries["tripadvisor"] = [
            f'"{restaurant_name}" {anchor} site:tripadvisor.com.hk',
            f'"{restaurant_name}" {anchor} tripadvisor 评分',
        ]
        queries["dianping"] = [
            f'"{restaurant_name}" {anchor} site:dianping.com',
            f'"{restaurant_name}" {anchor} 大众点评',
        ]
        queries["xiaohongshu"] = [
            f'"{restaurant_name}" {anchor} site:xiaohongshu.com',
            f'"{restaurant_name}" {anchor} 小红书',
        ]

    elif region == REGION_MAINLAND:
        # ===== 内地模式：四大厂商各 20% + 综合 20% =====
        
        # 大众点评（美团）：消费评价最全
        queries["dianping"] = [
            f'site:dianping.com "{restaurant_name}" {anchor}',
            f'"{restaurant_name}" {anchor} 大众点评 评分',
        ]

        # 抖音（字节）：视频种草+本地生活
        queries["douyin"] = [
            f'"{restaurant_name}" {anchor} site:douyin.com',
            f'"{restaurant_name}" {anchor} 抖音 推荐',
        ]

        # 小红书：种草内容
        queries["xiaohongshu"] = [
            f'"{restaurant_name}" {anchor} site:xiaohongshu.com',
            f'"{restaurant_name}" {anchor} 小红书',
        ]

        # 高德（阿里本地生活）：到店+地图评价
        queries["gaode"] = [
            f'"{restaurant_name}" {anchor} site:amap.com OR site:gaode.com',
            f'"{restaurant_name}" {anchor} 高德 评分',
        ]

        # 综合：新闻/旅游平台/微博等第三方视角
        queries["general"] = [
            f'"{restaurant_name}" {anchor} 评价 新闻',
            f'"{restaurant_name}" {anchor} site:weibo.com OR site:ctrip.com',
        ]

    elif region == REGION_TAIWAN:
        # ===== 台湾模式：复用港澳逻辑 =====
        queries["openrice"] = [
            f'site:openrice.com "{restaurant_name}" {anchor}',
            f'"{restaurant_name}" {anchor} openrice',
        ]
        queries["google_maps"] = [
            f'"{restaurant_name}" {anchor} Google Maps 评分',
        ]
        queries["tripadvisor"] = [
            f'"{restaurant_name}" {anchor} tripadvisor 评分',
        ]
        queries["dianping"] = [
            f'"{restaurant_name}" {anchor} 大众点评',
        ]
        queries["xiaohongshu"] = [
            f'"{restaurant_name}" {anchor} 小红书',
        ]

    else:
        # ===== 海外模式 =====
        queries["google_maps"] = [
            f'"{restaurant_name}" {anchor} Google Maps',
        ]
        queries["tripadvisor"] = [
            f'"{restaurant_name}" {anchor} tripadvisor',
        ]
        queries["dianping"] = [
            f'"{restaurant_name}" {anchor} 大众点评',
        ]
        queries["xiaohongshu"] = [
            f'"{restaurant_name}" {anchor} 小红书',
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
    # 平台权重：按区域动态取
    region = CITY_REGIONS.get(city_name, REGION_MAINLAND)
    platform_weights_map = REGION_PLATFORM_WEIGHTS.get(region, REGION_PLATFORM_WEIGHTS[REGION_MAINLAND])
    # score_result 用的加分值 = 权重 * 30（保持和原来数量级一致）
    platform_weight = platform_weights_map.get(platform, 0.15) * 30
    if any(d in domain for d in PLATFORM_DOMAINS.get(platform, [])):
        score += platform_weight
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


def extract_platform_signals(results: list, platform: str) -> dict:
    """
    从搜索摘要中提取权威平台的硬指标（评分/评论数/价格/排名）。
    
    核心思路：不抓详情页（反爬严重），只解析搜索引擎返回的摘要（snippet）。
    
    OpenRice 摘要格式："4.5 | 11175 灣仔 $101-200 意大利菜 薄餅"
    TripAdvisor 摘要格式："4.4分...排第914名...13,910家餐廳"
    Google Maps 摘要格式："4.3(258)" 或 "Rated 4.3/5 based on 258 reviews"
    
    返回：{
        "platform": str,
        "rating": float or None,
        "review_count": int or None,
        "price_range": str or None,
        "district": str or None,
        "rank": str or None,
        "data_completeness": float,  # 0.0 - 1.0
        "missing_fields": list,
    }
    """
    signals = {
        "platform": platform,
        "rating": None,
        "review_count": None,
        "price_range": None,
        "district": None,
        "rank": None,
        "data_completeness": 0.0,
        "missing_fields": [],
    }
    
    # 合并所有结果的 title + snippet
    combined_text = ""
    for item in results:
        combined_text += f" {item.get('title', '')} {item.get('snippet', '')}"
    
    if not combined_text.strip():
        signals["missing_fields"] = ["rating", "review_count", "price_range", "rank"]
        return signals
    
    found_fields = 0
    total_fields = 4  # rating, review_count, price_range, rank
    
    # ===== OpenRice 解析 =====
    if platform == "openrice":
        # 格式："4.5 | 11175 灣仔 $101-200"
        or_pattern = re.compile(r'(\d+\.\d+)\s*\|\s*(\d+)\s+(\S+)\s+(\$\d+(?:-\d+)?)')
        match = or_pattern.search(combined_text)
        if match:
            signals["rating"] = float(match.group(1))
            signals["review_count"] = int(match.group(2))
            signals["district"] = match.group(3)
            signals["price_range"] = match.group(4)
            found_fields += 3  # rating + review_count + price_range
        else:
            # 降级：仅提取评分
            rating_match = re.search(r'(\d+\.\d+)\s*\|', combined_text)
            if rating_match:
                signals["rating"] = float(rating_match.group(1))
                found_fields += 1
            # 降级：仅提取价格
            price_match = re.search(r'\$(\d+)(?:-(\d+))?', combined_text)
            if price_match:
                signals["price_range"] = price_match.group(0)
                found_fields += 1
    
    # ===== TripAdvisor 解析 =====
    elif platform == "tripadvisor":
        # 格式1 中文："4.4分...40則則評論...排第914名...13,910家餐廳"
        # 格式2 英文："rated 4.0 of 5...40 unbiased reviews...ranked #9,991 of 13,886"
        rating_match = re.search(r'(\d+\.\d+)\s*分|rated\s+(\d+\.\d+)\s*of\s*5', combined_text, re.IGNORECASE)
        if rating_match:
            signals["rating"] = float(rating_match.group(1) or rating_match.group(2))
            found_fields += 1
        
        review_match = re.search(r'(\d+).*?評論|(\d+)\s*unbiased\s*reviews|(\d+)\s*reviews', combined_text, re.IGNORECASE)
        if review_match:
            count_str = review_match.group(1) or review_match.group(2) or review_match.group(3)
            signals["review_count"] = int(count_str)
            found_fields += 1
        
        # 中文排名："排第914名"
        rank_match = re.search(r'排第\s*(\d+)\s*名', combined_text)
        if rank_match:
            rank_num = rank_match.group(1)
            total_match = re.search(r'([\d,]+)\s*家餐廳|([\d,]+)\s*restaurants', combined_text, re.IGNORECASE)
            if total_match:
                total_str = (total_match.group(1) or total_match.group(2)).replace(",", "")
                signals["rank"] = f"第{rank_num}/{total_str}名"
            else:
                signals["rank"] = f"第{rank_num}名"
            found_fields += 1
        else:
            # 英文排名："ranked #9,991 of 13,886"
            rank_match_en = re.search(r'ranked\s*#?([\d,]+)\s*of\s*([\d,]+)', combined_text, re.IGNORECASE)
            if rank_match_en:
                r = rank_match_en.group(1).replace(",", "")
                t = rank_match_en.group(2).replace(",", "")
                signals["rank"] = f"第{r}/{t}名"
                found_fields += 1
        
        price_match = re.search(r'\$(\d+)(?:-(\d+))?', combined_text)
        if price_match:
            signals["price_range"] = price_match.group(0)
    
    # ===== Google Maps 解析 =====
    elif platform == "google_maps":
        # 格式："4.3(258)" 或 "Rated 4.3/5" 或 "4.3 · 258 reviews"
        rating_match = re.search(r'(\d+\.\d+)\s*(?:/\s*5|\s*·|\()', combined_text)
        if rating_match:
            signals["rating"] = float(rating_match.group(1))
            found_fields += 1
        
        # 评论数：(258) 或 "258 reviews" 或 "258则评论"
        review_match = re.search(r'\((\d[\d,]*)\)|(\d[\d,]*)\s*(?:reviews|则|條)', combined_text, re.IGNORECASE)
        if review_match:
            count_str = review_match.group(1) or review_match.group(2)
            signals["review_count"] = int(count_str.replace(",", ""))
            found_fields += 1
        
        price_match = re.search(r'\$\d+(?:-\d+)?|HKD\s*\d+', combined_text)
        if price_match:
            signals["price_range"] = price_match.group(0)
    
    # ===== 大众点评解析 =====
    elif platform == "dianping":
        rating_match = re.search(r'(\d+\.\d+)\s*分', combined_text)
        if rating_match:
            signals["rating"] = float(rating_match.group(1))
            found_fields += 1
        
        review_match = re.search(r'(\d+)\s*条?\s*评论', combined_text)
        if review_match:
            signals["review_count"] = int(review_match.group(1))
            found_fields += 1
        
        price_match = re.search(r'人均[：:]?\s*[¥￥$]?\s*(\d+)', combined_text)
        if price_match:
            signals["price_range"] = f"¥{price_match.group(1)}"
            found_fields += 1
    
    # ===== 抖音解析 =====
    elif platform == "douyin":
        # 抖音搜索摘要通常没有结构化评分，尝试提取
        rating_match = re.search(r'(\d+\.\d+)\s*分', combined_text)
        if rating_match:
            signals["rating"] = float(rating_match.group(1))
            found_fields += 1
        
        # 抖音常见格式：播放量/点赞数
        like_match = re.search(r'(\d+(?:\.\d+)?)\s*万?\s*(?:赞|点赞|喜欢)', combined_text)
        if like_match:
            like_str = like_match.group(1)
            if '万' in combined_text[like_match.start():like_match.start()+20]:
                signals["review_count"] = int(float(like_str) * 10000)
            else:
                signals["review_count"] = int(float(like_str))
            found_fields += 1
        
        price_match = re.search(r'人均[：:]?\s*[¥￥$]?\s*(\d+)', combined_text)
        if price_match:
            signals["price_range"] = f"¥{price_match.group(1)}"
            found_fields += 1
    
    # ===== 高德解析 =====
    elif platform == "gaode":
        rating_match = re.search(r'(\d+\.\d+)\s*分', combined_text)
        if rating_match:
            signals["rating"] = float(rating_match.group(1))
            found_fields += 1
        
        # 评论数/评价数
        review_match = re.search(r'(\d+)\s*[条口]评价', combined_text)
        if review_match:
            signals["review_count"] = int(review_match.group(1))
            found_fields += 1
        
        price_match = re.search(r'人均[：:]?\s*[¥￥$]?\s*(\d+)', combined_text)
        if price_match:
            signals["price_range"] = f"¥{price_match.group(1)}"
            found_fields += 1
    
    # ===== 综合搜索解析（新闻/旅游/微博）=====
    elif platform == "general":
        # 综合搜索以定性信号为主，尝试提取评分
        rating_match = re.search(r'(\d+\.\d+)\s*分', combined_text)
        if rating_match:
            signals["rating"] = float(rating_match.group(1))
            found_fields += 1
        
        price_match = re.search(r'人均[：:]?\s*[¥￥$]?\s*(\d+)', combined_text)
        if price_match:
            signals["price_range"] = f"¥{price_match.group(1)}"
            found_fields += 1
    
    # 计算数据完整度
    signals["data_completeness"] = round(found_fields / total_fields, 2)
    
    # 标记缺失字段
    if signals["rating"] is None:
        signals["missing_fields"].append("rating")
    if signals["review_count"] is None:
        signals["missing_fields"].append("review_count")
    if signals["price_range"] is None:
        signals["missing_fields"].append("price_range")
    if signals["rank"] is None and platform in ["tripadvisor"]:
        signals["missing_fields"].append("rank")
    
    return signals


def collect_search_bundle(target: dict) -> dict:
    """
    搜索策略入口：
    1. 权威平台精准搜索 → 解析摘要提取硬指标
    2. 如果关键数据缺失，补搜一轮
    3. 社交平台搜索（热度参考）
    """
    queries = platform_queries(target)
    city = target.get("city", "香港")
    bundle = {
        "target": target,
        "platforms": {},
        "platform_signals": {},  # 新增：摘要提取的硬指标
    }

    for platform, query_list in queries.items():
        best_summary = None
        for query in query_list:
            raw_results = search_web(query, platform=platform, city=city)
            filtered = filter_platform_results(raw_results, target, platform)
            summary = summarize_platform_result(platform, query, filtered)
            if not best_summary or summary["signal_strength"] > best_summary["signal_strength"]:
                best_summary = summary
            if summary["signal_strength"] == "high":
                break
        bundle["platforms"][platform] = best_summary or summarize_platform_result(platform, query_list[0], [])
        
        # 从搜索摘要中提取硬指标
        filtered_results = best_summary.get("results", []) if best_summary else []
        signals = extract_platform_signals(filtered_results, platform)
        bundle["platform_signals"][platform] = signals
    
    # ===== 补搜策略：关键数据缺失时追加搜索 =====
    # 根据区域判断权威平台
    region = CITY_REGIONS.get(city, REGION_MAINLAND)
    if region == REGION_MAINLAND:
        authority_platforms = ["dianping", "douyin", "xiaohongshu", "gaode"]
    elif region == REGION_HK_MACAU:
        authority_platforms = ["openrice", "google_maps", "tripadvisor"]
    else:
        authority_platforms = ["google_maps"]
    
    has_any_rating = any(
        bundle["platform_signals"].get(p, {}).get("rating") is not None
        for p in authority_platforms
    )
    
    if not has_any_rating:
        # 补搜：用更宽泛的关键词
        restaurant_name = target["brand_name"]
        anchor = target.get("branch_candidates", [city])[0]
        
        bonus_query = f'{restaurant_name} {anchor} 評分 review rating'
        bonus_results = search_web(bonus_query, city=city)
        bonus_filtered = filter_platform_results(bonus_results, target, "generic")
        
        # 尝试从补搜结果中提取信号
        for item in bonus_filtered:
            url = item.get("url", "")
            snippet = item.get("snippet", "")
            title = item.get("title", "")
            combined = f"{title} {snippet}"
            
            # 识别是哪个平台的结果
            detected_platform = None
            if "openrice.com" in url:
                detected_platform = "openrice"
            elif "tripadvisor" in url:
                detected_platform = "tripadvisor"
            elif "google.com/maps" in url or "google.com" in url:
                detected_platform = "google_maps"
            elif "dianping.com" in url:
                detected_platform = "dianping"
            elif "douyin.com" in url:
                detected_platform = "douyin"
            elif "amap.com" in url or "gaode.com" in url:
                detected_platform = "gaode"
            elif "xiaohongshu.com" in url:
                detected_platform = "xiaohongshu"
            
            if detected_platform and bundle["platform_signals"].get(detected_platform, {}).get("rating") is None:
                new_signals = extract_platform_signals([item], detected_platform)
                # 如果新提取到评分，覆盖之前的空信号
                if new_signals["rating"] is not None:
                    bundle["platform_signals"][detected_platform] = new_signals
    
    return bundle


def _get_display_name(platform: str, city_name: str = "") -> str:
    """根据区域获取平台显示名"""
    region = CITY_REGIONS.get(city_name, REGION_MAINLAND)
    names = REGION_DISPLAY_NAMES.get(region, PLATFORM_DISPLAY_NAMES)
    return names.get(platform, platform)


def _get_platform_domains(platform: str, city_name: str = "") -> list:
    """根据区域获取平台域名列表"""
    region = CITY_REGIONS.get(city_name, REGION_MAINLAND)
    domains_map = REGION_DOMAINS.get(region, PLATFORM_DOMAINS)
    return domains_map.get(platform, [])


def _get_region_label(city_name: str) -> str:
    """获取区域模式中文标签"""
    region = CITY_REGIONS.get(city_name, REGION_MAINLAND)
    labels = {
        REGION_HK_MACAU: "🇭🇰 港澳模式",
        REGION_MAINLAND: "🇨🇳 内地模式",
        REGION_TAIWAN: "🇹🇼 台湾模式",
        REGION_OVERSEAS: "🌍 海外模式",
    }
    return labels.get(region, "🇨🇳 内地模式")


def format_search_bundle(bundle: dict) -> str:
    target = bundle["target"]
    strong = []
    weak = []
    platform_signals = bundle.get("platform_signals", {})
    
    lines = [
        "## 目标门店定位",
        f"- 用户输入：{target['input_name']}",
        f"- 城市：{target['city']}",
        f"- 区域模式：{_get_region_label(target['city'])}",
        f"- 判定：{'品牌/连锁型输入' if target['is_chain_like'] else '更像单店输入'}",
        f"- 疑似分店锚点：{', '.join(target.get('branch_candidates', [])) if target.get('branch_candidates') else '未识别到'}",
        f"- 定位置信度：{target['confidence']}",
        f"- 说明：{target['notes']}",
        "",
        "## 检索概览",
    ]
    city_name = target.get("city", "")
    for platform, summary in bundle.get("platforms", {}).items():
        name = _get_display_name(platform, city_name)
        if summary.get("signal_strength") in ["high", "medium"]:
            strong.append(name)
        else:
            weak.append(name)

    lines.append(f"- 高命中平台：{', '.join(strong) if strong else '无'}")
    lines.append(f"- 弱命中/无命中平台：{', '.join(weak) if weak else '无'}")
    
    # 摘要硬指标汇总
    lines.append("")
    lines.append("## 摘要提取硬指标")
    for platform, sig in platform_signals.items():
        name = _get_display_name(platform, city_name)
        parts = []
        if sig.get("rating") is not None:
            parts.append(f"⭐{sig['rating']}")
        if sig.get("review_count") is not None:
            parts.append(f"💬{sig['review_count']:,}")
        if sig.get("price_range") is not None:
            parts.append(f"💰{sig['price_range']}")
        if sig.get("rank") is not None:
            parts.append(f"🏅{sig['rank']}")
        if sig.get("district") is not None:
            parts.append(f"📍{sig['district']}")
        
        if parts:
            lines.append(f"- {name}：{' | '.join(parts)}（完整度 {sig.get('data_completeness', 0):.0%}）")
        else:
            lines.append(f"- {name}：未提取到量化数据")
    
    # 数据完整度总评
    region = CITY_REGIONS.get(city_name, REGION_MAINLAND)
    if region == REGION_MAINLAND:
        authority_keys = ["dianping", "douyin", "xiaohongshu", "gaode"]
    elif region == REGION_HK_MACAU:
        authority_keys = ["openrice", "google_maps", "tripadvisor"]
    else:
        authority_keys = ["google_maps", "tripadvisor", "openrice"]
    
    authority_data = {p: platform_signals.get(p, {}) for p in authority_keys if platform_signals.get(p)}
    completeness_values = [d.get("data_completeness", 0) for d in authority_data.values()]
    avg_completeness = sum(completeness_values) / len(completeness_values) if completeness_values else 0
    
    if avg_completeness >= 0.7:
        lines.append(f"\n📊 整体完整度：{avg_completeness:.0%} ✅ 权威数据充分，结论可信")
    elif avg_completeness >= 0.3:
        lines.append(f"\n📊 整体完整度：{avg_completeness:.0%} ⚠️ 部分数据缺失，结论仅供参考")
    else:
        lines.append(f"\n📊 整体完整度：{avg_completeness:.0%} 🔴 数据严重不足，结论不可靠")

    for platform, summary in bundle.get("platforms", {}).items():
        name = _get_display_name(platform, city_name)

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

    # ===== 1. 线索猎犬：平台证据汇总（含摘要硬指标）=====
    platform_scores = {}
    platform_reviews = {}
    platform_signals = search_bundle.get("platform_signals", {})
    
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
        name = _get_display_name(pkey, city)
        sig = platform_signals.get(pkey, {})
        
        # 构建硬指标行
        hard_data = ""
        if sig.get("rating"):
            hard_data += f"⭐{sig['rating']}"
        if sig.get("review_count"):
            hard_data += f" 💬{sig['review_count']:,}"
        if sig.get("price_range"):
            hard_data += f" 💰{sig['price_range']}"
        if sig.get("rank"):
            hard_data += f" 🏅{sig['rank']}"
        
        if summary and summary.get("matched"):
            strength = summary.get("signal_strength", "low")
            top = summary.get("top_result", {})
            snippet = (top.get("snippet", "") or "")[:80]
            if hard_data:
                search_lines.append(f"- {name}：{hard_data} | 信号 {strength} | {snippet}...")
            else:
                search_lines.append(f"- {name}：信号强度 {strength} | 质量分 {top.get('quality_score', 0):.1f} | {snippet}...")
        else:
            search_lines.append(f"- {name}：未命中高质量结果")
    
    # 数据完整度总结
    region = CITY_REGIONS.get(city, REGION_MAINLAND)
    if region == REGION_MAINLAND:
        authority_keys = ["dianping", "douyin", "xiaohongshu", "gaode"]
    elif region == REGION_HK_MACAU:
        authority_keys = ["openrice", "google_maps", "tripadvisor"]
    else:
        authority_keys = ["google_maps", "tripadvisor", "openrice"]
    authority_data = {p: platform_signals.get(p, {}) for p in authority_keys if platform_signals.get(p)}
    completeness_values = [d.get("data_completeness", 0) for d in authority_data.values()]
    avg_completeness = sum(completeness_values) / len(completeness_values) if completeness_values else 0
    
    if avg_completeness >= 0.7:
        search_lines.append(f"\n📊 数据完整度：{avg_completeness:.0%} — 权威平台数据较充分")
    elif avg_completeness >= 0.3:
        search_lines.append(f"\n📊 数据完整度：{avg_completeness:.0%} — 部分关键数据缺失，结论仅供参考")
    else:
        search_lines.append(f"\n📊 数据完整度：{avg_completeness:.0%} — 权威数据严重不足，结论不可靠")
    
    # 缺失字段汇总
    all_missing = set()
    for sig in platform_signals.values():
        all_missing.update(sig.get("missing_fields", []))
    if all_missing:
        field_names = {"rating": "评分", "review_count": "评论数", "price_range": "价格", "rank": "排名"}
        missing_names = [field_names.get(f, f) for f in all_missing]
        search_lines.append(f"⚠️ 缺失项：{', '.join(missing_names)}")

    expert_search = "\n".join(search_lines)

    # ===== 2. 拆台师：跨平台矛盾检测（含评分对比）=====
    contradictions = []
    scores = {}
    for pkey, summary in platforms.items():
        if summary and summary.get("matched"):
            scores[pkey] = summary.get("signal_strength", "low")

    # ⭐ 核心新增：基于摘要硬指标的评分矛盾检测
    ratings_from_signals = {}
    for pkey, sig in platform_signals.items():
        if sig.get("rating") is not None:
            ratings_from_signals[pkey] = sig["rating"]
    
    if len(ratings_from_signals) >= 2:
        rating_values = list(ratings_from_signals.values())
        rating_range = max(rating_values) - min(rating_values)
        rating_platforms = [f"{_get_display_name(k, city)}({v})" for k, v in ratings_from_signals.items()]
        
        if rating_range >= 0.8:
            contradictions.append(f"⚠️ 跨平台评分差异大（{rating_range:.1f}分）：{', '.join(rating_platforms)}，需警惕")
        elif rating_range >= 0.3:
            contradictions.append(f"跨平台评分存在差异（{rating_range:.1f}分）：{', '.join(rating_platforms)}")
        else:
            contradictions.append(f"跨平台评分基本一致（差异{rating_range:.1f}分）：{', '.join(rating_platforms)}")
    elif len(ratings_from_signals) == 1:
        p, r = list(ratings_from_signals.items())[0]
        contradictions.append(f"仅 {_get_display_name(p, city)} 有评分（{r}），缺少交叉验证")

    # 信号强度不一致
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
    or_sig = platform_signals.get("openrice", {})
    if or_sig.get("rating") is not None:
        or_line = f"OpenRice 评分 {or_sig['rating']}/5"
        if or_sig.get("review_count"):
            or_line += f"（{or_sig['review_count']:,} 条评论）"
        or_line += " — 香港本地食客视角，可信度高"
        review_quality.append(or_line)
    elif or_summary and or_summary.get("matched"):
        review_quality.append("OpenRice 有信号但未提取到评分/评论数，缺少量化指标")
    else:
        review_quality.append("⚠️ OpenRice 无信号 — 缺少香港本地食客视角，验证基础薄弱")

    # TripAdvisor 评论
    ta_summary = platforms.get("tripadvisor")
    ta_sig = platform_signals.get("tripadvisor", {})
    if ta_sig.get("rating") is not None:
        ta_line = f"TripAdvisor 评分 {ta_sig['rating']}/5"
        if ta_sig.get("review_count"):
            ta_line += f"（{ta_sig['review_count']} 条评论）"
        if ta_sig.get("rank"):
            ta_line += f"，排名 {ta_sig['rank']}"
        ta_line += " — 以游客评价为主，参考价值有限"
        review_quality.append(ta_line)
    elif ta_summary and ta_summary.get("matched"):
        review_quality.append("TripAdvisor 有信号但未提取到量化指标")
    
    # Google Maps 评论
    gm_sig = platform_signals.get("google_maps", {})
    if gm_sig.get("rating") is not None:
        gm_line = f"Google Maps 评分 {gm_sig['rating']}/5"
        if gm_sig.get("review_count"):
            gm_line += f"（{gm_sig['review_count']:,} 条评论）"
        gm_line += " — 全球通用，评分相对客观"
        review_quality.append(gm_line)

    expert_review = "\n".join([f"- {r}" for r in review_quality]) if review_quality else "- 评论样本不足，无法判断质量"

    # ===== 4. 街坊雷达：本地认可度（含评分硬指标）=====
    local_signals = []
    region = CITY_REGIONS.get(city, REGION_MAINLAND)
    has_openrice = platforms.get("openrice") and platforms.get("openrice").get("matched")
    has_dianping = platforms.get("dianping") and platforms.get("dianping").get("matched")
    has_xhs = platforms.get("xiaohongshu") and platforms.get("xiaohongshu").get("matched")
    has_ta = platforms.get("tripadvisor") and platforms.get("tripadvisor").get("matched")
    has_douyin = platforms.get("douyin") and platforms.get("douyin").get("matched")
    
    or_sig = platform_signals.get("openrice", {})
    gm_sig = platform_signals.get("google_maps", {})
    ta_sig = platform_signals.get("tripadvisor", {})
    dp_sig = platform_signals.get("dianping", {})
    dy_sig = platform_signals.get("douyin", {})

    if region == REGION_HK_MACAU:
        # 港澳：OpenRice 是本地认可度核心指标
        if or_sig.get("rating") is not None:
            or_line = f"OpenRice {or_sig['rating']}/5"
            if or_sig.get("review_count"):
                or_line += f"（{or_sig['review_count']:,}条评论）"
            or_line += " → 本地食客认可"
            local_signals.append(or_line)
        elif has_openrice:
            local_signals.append("OpenRice 有信号但无量化评分 → 本地讨论度存在，但无法量化")
        else:
            local_signals.append("⚠️ OpenRice 无信号 → 本地食客讨论度低，可能是游客店或新店")
    elif region == REGION_MAINLAND:
        # 内地：大众点评是本地认可度核心指标
        if dp_sig.get("rating") is not None:
            dp_line = f"大众点评 {dp_sig['rating']}/5"
            if dp_sig.get("review_count"):
                dp_line += f"（{dp_sig['review_count']:,}条评论）"
            dp_line += " → 消费者真实评价"
            local_signals.append(dp_line)
        elif has_dianping:
            local_signals.append("大众点评有信号但无量化评分 → 讨论度存在，但无法量化")
        else:
            local_signals.append("⚠️ 大众点评无信号 → 消费者讨论度低，可能是新店或冷门店")
        
        # 抖音信号
        if dy_sig.get("rating") is not None:
            dy_line = f"抖音 {dy_sig['rating']}/5"
            if dy_sig.get("review_count"):
                dy_line += f"（{dy_sig['review_count']:,}赞）"
            dy_line += " → 视频种草热度"
            local_signals.append(dy_line)
        elif has_douyin:
            local_signals.append("抖音有信号 → 视频种草存在，需注意营销密度")

    if gm_sig.get("rating") is not None:
        gm_line = f"Google Maps {gm_sig['rating']}/5"
        if gm_sig.get("review_count"):
            gm_line += f"（{gm_sig['review_count']:,}条）"
        local_signals.append(gm_line)

    if has_dianping and region == REGION_HK_MACAU:
        local_signals.append("大众点评有信号 → 内地游客有关注")

    # 关键判断：本地认可 vs 游客热度（按区域不同逻辑）
    if region == REGION_HK_MACAU:
        or_has_data = or_sig.get("rating") is not None
        xhs_has_data = has_xhs
        ta_has_data = ta_sig.get("rating") is not None
        
        if xhs_has_data and not or_has_data:
            local_signals.append("🔴 小红书热度高但 OpenRice 无评分 → 更可能是'游客热'而非'本地认可'")
        elif xhs_has_data and or_has_data:
            local_signals.append("🟢 小红书 + OpenRice 双平台有评分 → 游客和本地都有一定认可")
        
        if ta_has_data and not or_has_data:
            local_signals.append("🟡 TripAdvisor 有评分但 OpenRice 无 → 纯游客店特征明显")
        
        # 评分差距判断
        if or_sig.get("rating") and ta_sig.get("rating"):
            diff = or_sig["rating"] - ta_sig["rating"]
            if diff >= 0.5:
                local_signals.append(f"本地评分({or_sig['rating']})高于游客评分({ta_sig['rating']}) → 本地人更认可")
            elif diff <= -0.5:
                local_signals.append(f"游客评分({ta_sig['rating']})高于本地评分({or_sig['rating']}) → 可能被游客滤镜抬高")
    
    elif region == REGION_MAINLAND:
        dp_has_data = dp_sig.get("rating") is not None
        xhs_has_data = has_xhs
        dy_has_data = has_douyin
        
        if xhs_has_data and not dp_has_data:
            local_signals.append("🔴 小红书热度高但大众点评无评分 → 更可能是'种草热'而非'消费认可'")
        elif xhs_has_data and dp_has_data:
            local_signals.append("🟢 小红书 + 大众点评双平台有评分 → 种草和消费评价都有")
        
        if dy_has_data and not dp_has_data:
            local_signals.append("🟡 抖音有热度但大众点评无评分 → 视频营销盘特征")
        
        # 评分差距判断（大众点评 vs 小红书情绪）
        if dp_sig.get("rating") and gm_sig.get("rating"):
            diff = dp_sig["rating"] - gm_sig["rating"]
            if diff >= 0.5:
                local_signals.append(f"大众点评({dp_sig['rating']})高于 Google Maps({gm_sig['rating']}) → 国内消费者更认可")
            elif diff <= -0.5:
                local_signals.append(f"Google Maps({gm_sig['rating']})高于大众点评({dp_sig['rating']}) → 国际视角与国内评价分歧")
    
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

    # ===== 6. 收口官：综合裁决（含评分量化 + 数据完整度）=====
    # 优先使用摘要提取的真实评分，降级使用信号强度
    weighted_score = 0
    total_weight = 0
    # 根据区域动态获取平台权重
    region = CITY_REGIONS.get(city, REGION_MAINLAND)
    platform_weights_judge = REGION_PLATFORM_WEIGHTS.get(region, REGION_PLATFORM_WEIGHTS[REGION_MAINLAND])
    
    # 量化评分：将真实评分归一化到 0-1 区间
    has_real_rating = False
    for pkey, sig in platform_signals.items():
        if sig.get("rating") is not None:
            weight = platform_weights_judge.get(pkey, 0.15)
            # 评分归一化：5分制 → 0-1（3.0以下算0，5.0算1）
            normalized = max(0, min(1, (sig["rating"] - 3.0) / 2.0))
            weighted_score += normalized * weight
            total_weight += weight
            has_real_rating = True
    
    # 降级：没有真实评分时用信号强度
    if not has_real_rating:
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
    if not (platforms.get("openrice") and platforms.get("openrice").get("matched")) and \
       not (platforms.get("dianping") and platforms.get("dianping").get("matched")):
        risk_tags.append("本地认可度不明")
    if target.get("branch_candidates"):
        risk_tags.append("多分店体验差异")
    
    # 数据完整度风险
    authority_data = {p: platform_signals.get(p, {}) for p in authority_keys if platform_signals.get(p)}
    completeness_values = [d.get("data_completeness", 0) for d in authority_data.values()]
    avg_completeness = sum(completeness_values) / len(completeness_values) if completeness_values else 0
    
    if avg_completeness < 0.3:
        risk_tags.append("⚠️ 数据严重不足")
    elif avg_completeness < 0.6:
        risk_tags.append("数据部分缺失")
    
    # 跨平台评分冲突
    ratings_from_signals = {p: sig["rating"] for p, sig in platform_signals.items() if sig.get("rating") is not None}
    if len(ratings_from_signals) >= 2:
        rating_range = max(ratings_from_signals.values()) - min(ratings_from_signals.values())
        if rating_range >= 0.8:
            risk_tags.append("跨平台评分冲突")

    judge_lines = [
        f"综合评分：{final_score:.2f}/1.00（{'基于真实评分量化' if has_real_rating else '仅基于信号强度，无量化评分'}）",
        f"数据完整度：{avg_completeness:.0%}（{'充分' if avg_completeness >= 0.7 else '部分缺失' if avg_completeness >= 0.3 else '严重不足'}）",
    ]
    
    # 列出各平台评分
    if ratings_from_signals:
        rating_parts = [f"{_get_display_name(p, city)} {r}" for p, r in ratings_from_signals.items()]
        judge_lines.append(f"各平台评分：{' / '.join(rating_parts)}")
    
    judge_lines.extend([
        f"裁决：{verdict}",
        f"踩雷风险：{risk}",
        f"置信度：{confidence}",
        f"风险标签：{', '.join(risk_tags) if risk_tags else '无明显风险标签'}",
    ])

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
    mvp = FoodBuddyMVP()

    print("🍴 老饕探案组已就位")
    print()
    print("哪家店？说城市和店名，我帮你验一验。")
    print()
    print("⚠️  跨平台搜索 + 营销过滤，尽力拼凑真相。拿不到的直说，不硬判。")
    print("（*即使搜到了也不敢打包票，hhh*）")
    print()
    print("我会跨平台采集证据、交叉验证，30 秒左右给你结论。\n")

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
                    print("说店名，担心什么也一并讲。")
                else:
                    print(f"\n暂不支持「{user_input}」，目前支持内地主要城市 + 港澳。")
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

                print("\n还有哪家想验？直接说，或 exit 退出。")

        except KeyboardInterrupt:
            print("\n\n下次见，愿你少踩雷。")
            break
        except Exception as e:
            print(f"\n❌ 出错了：{e}")


if __name__ == "__main__":
    interactive_mode()
