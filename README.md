# github-to-cloudflare — DSH 技能

把 GitHub 仓库或本地项目部署到 Cloudflare 的 DSH 技能：给一个 URL，判型 → 选通道 → 部署 → 验证 → 记账。

派生自 [hxx0611/github-to-cloudflare](https://github.com/hxx0611/github-to-cloudflare)（MIT，QwenPaw skill），针对本机环境重写并修了上游的 4 个问题。

## 安装

DSH 技能是「目录即技能」，放进技能目录即可，下个会话生效：

```bash
git clone https://github.com/tel9980/github-to-cloudflare-skill.git \
  ~/.dsh/skills/github-to-cloudflare
```

## 内容

| 文件 | 作用 |
|---|---|
| `SKILL.md` | 5 步 SOP（判型 / 选通道并确认 / 部署 / 验证 / 记账）+ 环境检查 + 报告模板 + 坑清单 |
| `scripts/analyze.py` | 离线判型：clone → 读 package.json / 框架配置 → 输出 plan JSON |
| `scripts/cf.py` | Cloudflare API 客户端（stdlib urllib，无需 curl） |
| `scripts/verify.sh` | 部署后验证：跟 302、重试、取 status 与 `<title>` |
| `scripts/ledger.py` | 部署账本，`state/deployments.json` |
| `references/channels.md` | A/B/C/D 四条通道的 curl / wrangler 精确命令 + 故障表 |
| `references/frameworks.md` | 20 种框架 → install / build / output / 通道 对照 |
| `references/actions.md` | wrangler-action@v4 的 GitHub Actions 模板 |

## 相对上游的改动

修 bug：

1. **token 不再落盘** — 上游把 token 拼进 remote URL，写进 `.git/config`；改为 `git -c http.https://github.com/.extraheader=Authorization: Bearer <token>`，已存在目录的 fetch 同样注入。
2. **`signals` 恢复有值** — 上游 `detect_one()` 把判型证据 append 到局部 list 后丢弃，`main()` 里 signals 恒为空；现在 plan 字典直接持有同一 list 引用。
3. **SvelteKit adapter 笔误** — `svelte-adapter=adapter-cloudflare` → `npm i -D @sveltejs/adapter-cloudflare`。
4. **monorepo 判型** — 上游对 workspace 根目录只报 `nodejs-no-framework`；现在识别为 `monorepo` 并列出候选子包。

环境适配（本机无 curl）：

- 新增 `scripts/cf.py`：`GET|POST|PATCH|PUT|DELETE <path> [--json|--json-file]`，`{account}` 自动替换 `CLOUDFLARE_ACCOUNT_ID`，token 只从环境变量读、输出自动 redact，缺凭证 exit 2。
- `scripts/verify.sh` 重写为纯 python3 urllib，单次请求同时拿 body 与 status。

新增：`scripts/ledger.py` 部署账本（同仓库不同 URL 写法归一，更新而非重复记）。

## 使用

需要两个环境变量（技能不会把 token 写进任何文件或输出）：

```bash
export CLOUDFLARE_API_TOKEN=...      # Edit Cloudflare Workers 模板，或自定义加 Pages: Edit
export CLOUDFLARE_ACCOUNT_ID=...
python3 scripts/cf.py --verify       # 冒烟
```

然后在 DSH 会话里说「把这个仓库部署到 Cloudflare + URL」，技能会自动触发。

只做判型、不碰 Cloudflare：

```bash
python3 scripts/analyze.py https://github.com/owner/repo --out /tmp/plan.json
```

## 许可

MIT，见 [LICENSE](LICENSE)。原始版权归 hxx0611。
