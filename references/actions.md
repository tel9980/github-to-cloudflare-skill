# GitHub Actions 部署模板（通道 C）

前置：repo secrets 设置 `CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID`
（gh CLI 不可用时让用户在 Settings → Secrets and variables → Actions 手工加）。

action 用 `cloudflare/wrangler-action@v4`（默认装 Wrangler v4；v3 仅存量）。

## T1 Workers / OpenNext Next.js

```yaml
name: Deploy to Cloudflare Workers
on:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22          # 对照 package.json engines
          cache: npm                # pnpm 用 pnpm/action-setup
      - run: npm ci
      - name: Build
        run: npm run build          # Next.js: npm run build && npx @opennextjs/cloudflare build
      - uses: cloudflare/wrangler-action@v4
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
```

## T2 Pages 项目走 Direct Upload（无 CF Git 集成时）

```yaml
name: Deploy Pages
on:
  push:
    branches: [main]
  pull_request:
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22 }
      - run: npm ci && npm run build
      - uses: cloudflare/wrangler-action@v4
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          command: pages deploy dist --project-name=<cf_name>
            --branch=${{ github.event_name == 'pull_request' && 'preview' || 'main' }}
            --commit-dirty=true
```

PR preview 更规范的做法：Pages 项目仍为 direct-upload 时，PR 用
`--branch=pr-${{ github.event.number }}`，合并后 main 分支部署自动成为正式。

## 写入仓库

```bash
mkdir -p .github/workflows && cat > .github/workflows/deploy.yml  # 粘贴模板
git add .github/workflows/deploy.yml && git commit -m "ci: deploy to Cloudflare"
git push   # 需要写权限；GH_TOKEN 走 https 时同 analyze.py 的注入方式
```

观察运行：Actions 页或（有 gh CLI 时）`gh run watch`。失败排查看 workflow log，
wrangler 报错常见为 token 权限（缺 Pages:Edit）或项目不存在（先跑一次 D 建项目）。
