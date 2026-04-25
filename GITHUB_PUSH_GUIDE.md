# GitHub 推送指南

本地仓库已初始化完成，现在需要推送到 GitHub。

## 方式一：GitHub CLI（推荐）

如果你已安装 `gh` 并已登录：

```bash
# 在仓库目录下
cd /Users/songqiaotian/WorkBuddy/Food-buddy/food-buddy-release

# 创建 GitHub 仓库并推送
gh repo create food-buddy --public --source=. --push

# 或使用已有仓库
gh repo create food-buddy --public --source=. --remote=origin --push
```

## 方式二：手动推送

### 第 1 步：在 GitHub 创建空仓库

1. 打开 https://github.com/new
2. 仓库名填：`food-buddy`
3. 选择 **Public**（或 Private）
4. **不要勾选** "Initialize this repository with a README"
5. 点击 "Create repository"

### 第 2 步：关联远程仓库并推送

```bash
cd /Users/songqiaotian/WorkBuddy/Food-buddy/food-buddy-release

# 添加远程仓库（将 YOUR_USERNAME 替换为你的 GitHub 用户名）
git remote add origin https://github.com/YOUR_USERNAME/food-buddy.git

# 推送
git branch -M main
git push -u origin main
```

## 方式三：SSH 推送

如果你配置了 SSH Key：

```bash
cd /Users/songqiaotian/WorkBuddy/Food-buddy/food-buddy-release

git remote add origin git@github.com:YOUR_USERNAME/food-buddy.git
git branch -M main
git push -u origin main
```

---

## 推送后检查

推送完成后，访问：
```
https://github.com/YOUR_USERNAME/food-buddy
```

确认：
- [ ] README.md 正确渲染
- [ ] 文件结构完整
- [ ] LICENSE 显示正确

---

## 后续维护

```bash
# 日常修改后提交
git add .
git commit -m "描述你的修改"
git push

# 创建标签（版本发布）
git tag -a v0.2.0 -m "MVP v2 release"
git push origin v0.2.0
```

---

## 仓库位置

本地仓库：`/Users/songqiaotian/WorkBuddy/Food-buddy/food-buddy-release`

如需修改后重新提交：
```bash
cd /Users/songqiaotian/WorkBuddy/Food-buddy/food-buddy-release
# 修改文件...
git add -A
git commit -m "你的修改描述"
git push
```
