# Food Buddy 试用说明

## 这是什么
这是一个"从网上种草到出发前验证"的餐厅防踩雷 Skill。

它不是全城推荐器，而是当你已经有一家目标餐厅时，帮你做真实搜索和交叉验证，判断：
- 值不值得去
- 会不会踩雷
- 是不是热度大于证据

## 目录结构
- `SKILL.md`：Skill 总说明
- `references/`：方法论与协议
- `prompts/experts/`：多 agent prompt
- `scripts/orchestrator.py`：MVP 入口脚本

## 快速开始

### 第 1 步：克隆或下载本项目

```bash
git clone <repo-url>
cd food-buddy
```

### 第 2 步：运行

```bash
python3 scripts/orchestrator.py
```

**由 OpenClaw Agent 驱动**，使用内置搜索和 LLM 能力完成验证。

### 第 3 步：输入验证请求
1. 先输入城市，例如：`香港`
2. 再输入餐厅，例如：`正斗，我想知道值不值得专门去`

## 工作原理

1. **搜索采集**：Agent 自动搜索 Google Maps / 大众点评 / 小红书 / OpenRice / TripAdvisor
2. **营销过滤**：自动过滤 SEO 农场站、种草文、营销内容
3. **多专家分析**：6 位专家基于搜索数据做结构化分析
4. **加权裁决**：OpenRice 权重最高（30%），TripAdvisor 权重最低（10%）

## 建议测试问题
- 香港的正斗怎么样
- 我在小红书上刷到桥底辣蟹很火，值得专门去吗
- 华嫂冰室会不会踩雷，我怕排队半天不值
- 鬼金棒在香港值不值得专门去

## 当前版本说明（MVP v2）
这是一个可试用的 MVP v2：
- ✅ 由 OpenClaw Agent 驱动，使用内置搜索和 LLM
- ✅ 已有营销噪音过滤系统
- ✅ 已有多 Agent 协作结构（6 位专家）
- ✅ 平台权重体系（OpenRice 权重最高，TripAdvisor 最低）
- ✅ 已升级为平台优先搜索（Google Maps / 大众点评 / 小红书 / OpenRice）

适合先验证"单店防踩雷"场景。还不是完整产品，但已经可以发给别人用了。
