# 部署通道 SOP（curl / wrangler 精确命令）

> **本机没有 curl 也能跑**：每条 `curl` 都有等价写法
> `python3 scripts/cf.py <METHOD> "<path>" [--json '<body>']`，path 里的
> `{account}` 会被 `CLOUDFLARE_ACCOUNT_ID` 替换。token 只从环境变量读，
> 不进 argv、不进输出。下文的 curl 命令照抄语义即可，参数名一一对应：
> `-X POST` → `POST`，`-d '<json>'` → `--json '<json>'`，`-H "$AUTH"` 自动加。

所有 API 调用前置：

```bash
export CLOUDFLARE_API_TOKEN=... CLOUDFLARE_ACCOUNT_ID=...
API=https://api.cloudflare.com/client/v4
AUTH="Authorization: Bearer $CLOUDFLARE_API_TOKEN"
```

冒烟测试（任何通道执行前必跑）：

```bash
curl -s -H "$AUTH" $API/user/tokens/verify        # 期望 "success":true
curl -s -H "$AUTH" "$API/accounts" | grep -o "$CLOUDFLARE_ACCOUNT_ID"
```

GitHub 仓库信息（通道 A 需要 owner/repo_name）：

```bash
# https://github.com/<owner>/<repo> → owner, repo
```

---

## A. Pages Git Integration（连续部署）

### A1 幂等检查

```bash
curl -s -H "$AUTH" $API/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/<name>
# success:true → 已存在，跳到 A3（或 A4 更新配置）
# "Could not find the project" → A2 创建
```

### A2 创建（source 指向 GitHub）

```bash
curl -s -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  $API/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects -d '{
  "name": "<cf_project_name>",
  "production_branch": "<default_branch>",
  "source": { "type": "github",
              "config": { "owner": "<owner>", "repo_name": "<repo>" } },
  "build_command": "<plan.build_command>",
  "destination_dir": "<plan.output_dir>",
  "build_caching": true,
  "deployment_configs": {
    "production": { "env_vars": { "NODE_VERSION": "22" },
                    "compatibility_date": "<plan.compatibility_date>" },
    "preview":    { "env_vars": { "NODE_VERSION": "22" } }
  }
}'
```

- monorepo 加 `"root_dir": "<pkg dir>"`。
- 无构建（纯静态提交）→ `"build_command": "()"`（Pages 约定的空操作）或省略。

### A3 **回读校验（不可跳过）**

2026-04 实战先例：create 请求 200，但 `env_vars`/`destination_dir` 前缀被**静默丢弃**。所以：

```bash
curl -s -H "$AUTH" $API/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/<name> \
  | python3 -c "import json,sys; p=json.load(sys.stdin)['result']; print(p.get('build_command'), p.get('destination_dir'), list(p.get('deployment_configs',{}).get('production',{}).get('env_vars',{})))"
```

字段与期望不符 → `PATCH` 同端点，body 用同样字段名补一遍，再 GET 确认。

### A4 触发部署 + 轮询

```bash
DEP=$(curl -s -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  $API/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/<name>/deployments \
  -d '{"branch":"<default_branch>"}' | python3 -c "import json,sys;print(json.load(sys.stdin)['result']['id'])")

for i in $(seq 1 30); do
  sleep 10
  S=$(curl -s -H "$AUTH" \
    $API/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/<name>/deployments/$DEP)
  echo "$S" | grep -qE '"status": *"(Success|success)"|"stage": *"Success"' && break
  echo "$S" | grep -qE 'build_failed|"failed"|canceled' && { echo "$S"; break; }
done
```

- 轮询字段以实际返回为准：重点看 `result.status` 与 `result.stages[].status`
  （Queued/Build/Deploy 三段）。
- 成功 → 生产 URL `https://<name>.pages.dev`，本次部署预览
  `result.url`（`<shortid>.<name>.pages.dev`）。
- 失败 → 看 `result.deployment_trigger.metadata`；报 GitHub 授权/集成类错误 →
  让用户到 dashboard Settings → Builds & deployments 重新授权 Cloudflare GitHub
  App，或降级通道 D。
- 之后每次 `git push` 到 production branch 自动重新构建，无需再操作。

### A5 Secrets 与自定义域名（可选）

```bash
# secrets：优先 wrangler（自动处理编码），避免手拼 API：
npx --yes wrangler pages secret put KEY_NAME --project-name=<name> --branch=<branch>
# 自定义域名（域名须托管在本 CF 账号）：
curl -s -X POST -H "$AUTH" -H 'Content-Type: application/json' \
  $API/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/<name>/domains \
  -d '{"name":"www.example.com"}'
```

---

## B. Workers + Static Assets

### B1 配置检查

需要 `wrangler.jsonc`（或 toml）：`name`、`main`（Worker 入口）、
`compatibility_date`（≤ 当天）、动态栈加 `compatibility_flags:
["nodejs_compat"]`、静态资源加 `"assets": { "directory": "dist",
"binding": "ASSETS" }`（纯静态 assets 可无 main）。缺文件时按 plan
`preconditions` 生成，生成后给用户过目。

### B2 构建 + 部署

```bash
cd <local_path> && <install_command> && <build_command>
export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID
OUT=$(npx --yes wrangler deploy 2>&1); echo "$OUT"
echo "$OUT" | grep -oE 'https://[a-z0-9._-]+\.workers\.dev' | head -1
```

Next.js（OpenNext）专用序列：

```bash
npm i -D @opennextjs/cloudflare wrangler@latest
# 或一步式（会 scaffold 配置并部署）：npx @opennextjs/cloudflare@latest deploy
npm run build && npx --yes @opennextjs/cloudflare build
npx --yes wrangler deploy
```

- 从 next-on-pages 迁移：先 `npm rm @cloudflare/next-on-pages` 并删
  `setupDevPlatform()` 相关代码，否则构建期两 adapter 冲突。
- 需要 secrets：`npx --yes wrangler secret put KEY`（值从 stdin 或交互输入，
  不进命令行参数）。

### B3 没有公开 URL 时

```bash
curl -s -H "$AUTH" $API/accounts/$CLOUDFLARE_ACCOUNT_ID/workers/subdomain
```

`enabled:false` → 让用户在 dashboard（Workers & Pages → 总览）开启
`*.workers.dev` 子域，或给 Worker 绑 routes/自定义域名（见 §E）。

---

## C. GitHub Actions

见 `actions.md`。要点：workflow 文件写进仓库需要 GitHub 写权限（用户自行 push
或提供有 write 的 GH_TOKEN）；repo secrets 至少
`CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID`。

## D. Direct Upload（兜底，无 git 集成）

```bash
npx --yes wrangler pages project create <name> --production-branch <branch> \
  || true   # 已存在会报错，幂等跳过
npx --yes wrangler pages deploy <output_dir> --project-name <name> --commit-dirty=true
```

输出含 `https://<name>.pages.dev`（正式）与 hashed preview URL。
注意：此项目**之后无法转为 git integration**；每次更新都要重跑 deploy 命令
（可作为通道 C 里 Actions 的命令）。

## E. Workers 自定义域名

`wrangler.jsonc` 加：

```jsonc
"routes": [{ "pattern": "example.com", "custom_domain": true }]
```

然后重跑 `wrangler deploy`。域名须托管在本 CF 账号。

## 故障速查

| 症状 | 原因 | 处置 |
|---|---|---|
| create 成功但 env 没生效 | API 静默丢弃字段 | A3 回读 + PATCH |
| Pages 部署一直 queued→failed 且报授权 | GitHub App 未装/授权过期 | dashboard 重授权，或降级 D |
| 正式域名没更新，但 preview 更新了 | push 的分支 ≠ production_branch | A4 用对的 branch 或改 production_branch |
| wrangler deploy 报缺 account | 环境变量没进子进程 | 同一 shell 内 export 后重跑 |
| deploy 成功但 workers.dev 404/不存在 | 子域未启用 | B3 |
| Next 构建报 edge runtime/Module not found | 残留 next-on-pages 或误配 edge | B2 迁移清理；OpenNext 默认 Node 运行时 |
| `output: 'export'` 项目在 OpenNext 下异常 | 两者互斥 | 改走静态通道 A/D |
| 构建镜像 Node 版本过老崩 | 未设 NODE_VERSION | env_vars 设 NODE_VERSION（对照 engines） |
