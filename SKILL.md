---
name: github-to-cloudflare
description: 把 GitHub 仓库或本地项目部署到 Cloudflare（Workers / Pages / Next.js OpenNext / Astro / SvelteKit / Nuxt / 静态站 / monorepo），包括"部署上线""发到 Cloudflare""push 自动部署""配 GitHub Actions"。给一个仓库 URL 或本地路径，自动判型、选通道、部署、验证并记账。不用于纯 CI 配置问答，也不用于 Vercel / Netlify / 自有服务器。
---

# GitHub → Cloudflare 部署

一句话：**一个 URL 进，一个能打开的链接出。判型离线做完，上云动作先问过用户。**

## 什么时候用

- 「把这个仓库部署到 Cloudflare」+ 任意 GitHub URL
- 「这个站能发到 CF 吗」「帮我把本地这个项目发上去」
- 要 push 自动上线、要 GitHub Actions 工作流
- 已有 CF Pages/Workers 项目，要更新、要排查「部署成功但打不开」

不适用：Vercel/Netlify/自建服务器迁移、纯 Cloudflare 账号账单问题、只问 DNS。

## 环境检查（每步开始前，只读）

```bash
python3 -V                     # 必需：analyze.py / cf.py / verify.sh 全靠它
python3 <skill>/scripts/cf.py --verify   # token + account 冒烟，缺凭证会直接说
node -v && npx --version       # 只有 B（Workers）和 D（direct upload）通道需要
```

`<skill>` = 本技能目录 `/root/.dsh/skills/github-to-cloudflare`。

- **本机没有 curl 是正常的**：`scripts/cf.py` 用 urllib 实现了同一套 Cloudflare API 调用，语法见下。文档里出现的 curl 都是等价示意，优先用 cf.py。
- 环境变量：`CLOUDFLARE_API_TOKEN`（Edit Cloudflare Workers 模板，或自定义加 Cloudflare Pages: Edit）、`CLOUDFLARE_ACCOUNT_ID`。
- **token 只走环境变量**：不 echo、不写进日志/回复/文件。`cf.py` 输出时自动把 token 替换成 `***REDACTED***`。
- 私有仓库才需要 `GITHUB_TOKEN`（repo read）；公开仓库不需要任何 GitHub 凭据。

## Step 1 — 判型（离线，可自动跑）

```bash
python3 <skill>/scripts/analyze.py <repo-url-or-path> [--branch main] \
        [--workdir /tmp/cfdeploys] [--out /tmp/plan.json]
```

输出 plan JSON 的关键字段：

| 字段 | 用途 |
|---|---|
| `type` | nextjs-opennext / nextjs-static-export / worker / vite-static / astro-static / hugo / static / monorepo … |
| `channel` | `pages-git`(A) / `workers-assets`(B) / `ask-user` |
| `build_command` / `output_dir` / `install_command` | 直接写进 Pages 项目配置或本地构建 |
| `cf_project_name` | 项目名（已按 CF 规则清洗，≤50 字符） |
| `compatibility_date` | 当天日期，Workers 配置用 |
| `preconditions` | 要补的配置文件/依赖，**先读这一段** |
| `signals` | 判型依据（`dep:next`、`config:wrangler.toml`、`file:hugo config`…），复核用 |
| `monorepo_packages` | monorepo 时的候选包子目录 |

纪律：

- `channel: ask-user` 或 `type: monorepo` → 把候选呈现给用户选，**别猜**。
- 判型与用户口头描述矛盾时，以 `signals` 为准，并明确指出证据。
- **来路不明的第三方仓库**：build 会执行任意 npm scripts，先确认再跑构建（供应链风险）。

## Step 2 — 选通道 + 向用户确认（不可跳过）

按 plan 的 `channel` 走，特殊情形：

- `workers-assets` 且 type 是 nextjs 家族 → OpenNext 子流程（含 next-on-pages 迁移清理）。
- 用户要「push 自动上线」+ 静态/SSG → 通道 A。
- 用户要「CI 跑在自己 GitHub 里」→ 通道 C。
- `next.config` 里有 `output: 'export'` → 静态通道 A/D，**别硬套 OpenNext**（互斥）。

确认消息里必须写清：类型判据摘要、通道、CF 项目名、将产生的 URL（`<name>.pages.dev` 或 `<name>.<subdomain>.workers.dev`）、需要的 env/secrets 名单。

**部署是对外发布动作。审批弹窗被关掉的会话里（本机常见），就用一条文字消息要明确同意再动手——不要拿「没人拦我」当授权。**

## Step 3 — 部署

命令细节全在 `references/channels.md`。用 cf.py 时把 `API` 前缀换成相对路径：

```bash
C=~/.dsh/skills/github-to-cloudflare/scripts
python3 $C/cf.py GET   "/accounts/{account}/pages/projects/<name>"
python3 $C/cf.py POST  "/accounts/{account}/pages/projects/<name>/deployments" --json '{"branch":"main"}'
python3 $C/cf.py PATCH "/accounts/{account}/pages/projects/<name>" --json-file /tmp/patch.json
```

- **A**：GET 查存在 → 不存在就 POST 建（`source.type=github`）→ **GET 回读校验 build 配置/env 是否被静默丢弃，缺了 PATCH 补** → POST 触发首次部署 → 轮询到 active 或失败。
- **B**：补 `wrangler.jsonc` → 本地 build → `npx --yes wrangler deploy` → 从输出抓 `https://*.workers.dev`；子域没启用见 §B3。
- **C**：把 `references/actions.md` 的模板写进仓库 `.github/workflows/deploy.yml`（需要写权限），提醒设 repo secrets。
- **D**：`wrangler pages project create`（先 list 查重）→ `wrangler pages deploy <out_dir>`。

失败先查 `references/channels.md` 的故障表；**同一条命令连续失败 2 次就换通道或问用户**，不要死循环。

## Step 4 — 验证

```bash
bash <skill>/scripts/verify.sh <url> [期望包含的关键字] [重试次数=3]
```

跟 302、重试、检查 200 与 `<title>`。Pages 首次过 CDN 可能 404/5xx，重试已覆盖。退出码 0 = 通了。

## Step 5 — 记账

```bash
python3 <skill>/scripts/ledger.py --add --repo <url> --project <cf_name> \
        --url <prod-url> --channel A|B|C|D --type <plan.type> [--preview <url>] [--note "..."]
python3 <skill>/scripts/ledger.py --list          # 全部记录
python3 <skill>/scripts/ledger.py --get <repo>    # 单条（下一步更新时读它）
```

存在 `state/deployments.json`。同一 repo 再来：先 `--get` 看旧记录，走更新流程（A 触发新 deployment / B 重跑 deploy），**不要重复建项目**。

## 最终报告模板

| 项目 | 类型 | 通道 | 生产 URL | 自动化 | 状态 |
|---|---|---|---|---|---|
| <cf_name> | <type> | <A/B/C/D> | <url> | push 自动 / 手动触发 | ✅ 200 |

附：preview URL、绑定分支、已配置的 secrets **名单**（只列名，不列值）、后续怎么更新。

## 已知坑（写操作前扫一眼）

- Pages 只有 **production branch** 的部署更新正式域名；其他分支只出 preview。
- Pages 构建镜像 Node 偏旧：`deployment_configs.*.env_vars` 里设 `NODE_VERSION`（对照 engines，常见 20/22）。
- Pages Git Integration 要求 Cloudflare GitHub App 已装到该仓库；报授权类错误 → dashboard 授权或降级 D。
- direct-upload 与 git-integration **不可互转**，选错只能删项目重建。
- OpenNext 与 `output:'export'` 互斥；装过 next-on-pages 的项目要先彻底移除（含 `setupDevPlatform()`）再换。
- 新账号 `*.workers.dev` 子域可能未启用 → 部署成功但没有公开 URL，这是「部署成功却打不开」的头号原因。
- wrangler 报 "Required requested account" → account 变量没进子进程。
- `compatibility_date` 不能超前于本地 wrangler 支持的日期；拿不准用 plan 里的（当天）。
- 静态站 `output_dir` 是 `.` 时（站点在仓库根），Pages 的 destination_dir 用 `.` 不稳，建议把站挪进子目录或改走 D 只发该目录。

## 维护

- 目录即技能：改 `SKILL.md` 的 frontmatter `description` 会影响何时被触发，改后在下个会话生效。
- 升级上游：`git -C /tmp/g2cf pull` 后**逐文件比对再合并**，别整目录覆盖——本地这份已经修过上游的 4 个问题（token 落盘、signals 丢失、svelte adapter 笔误、monorepo 判型）。
- 来源：https://github.com/hxx0611/github-to-cloudflare（MIT）。
