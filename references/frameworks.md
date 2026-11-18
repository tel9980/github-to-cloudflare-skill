# 框架判型 → 构建/产物对照表（2026-09 核实的官方口径）

| plan.type | 判型标记 | install | build_command | output_dir | 首选通道 | 备注 |
|---|---|---|---|---|---|---|
| static | index.html（根/public/dist/docs） | - | 无（"()"） | 命中目录 | A / D | 纯提交产物 |
| vite-static | deps 有 vite/react/vue/svelte（无 SSR 框架） | npm/pnpm | `npm run build` | `dist` | A | 也可 B（Assets-only Worker） |
| astro-static | astro，output 默认 static | 同上 | `npm run build` | `dist` | A | |
| astro-cloudflare-ssr | astro.config 引 @astrojs/cloudflare 或 output:server | 同上 | `npm run build` | `dist/_worker.js` | B | hybrid 已弃用，改 prerender |
| sveltekit-cloudflare | adapter-cloudflare | 同上 | `npm run build` | `.svelte-kit/cloudflare` | B | Pages 也吃得下这套产物 |
| sveltekit-static | adapter-static / adapter-auto | 同上 | `npm run build` | `build` | A | prerender 全静态才安全 |
| nuxt (generate) | nuxt，无 nitro cloudflare preset | 同上 | `npm run generate` | `dist` | A | SSR 要 preset cloudflare-module → B |
| nuxt-cloudflare-module | nitro.preset: cloudflare-module | 同上 | `npm run build` | `dist/_worker.js` | B | |
| docusaurus | deps docusaurus | 同上 | `npm run build` | `build` | A | |
| vuepress | deps @vuepress/* | 同上 | `npx vuepress build docs` | `docs/.vuepress/dist` | A | |
| gatsby / eleventy / hexo | 对应 deps | 同上 | build/generate | public/_site/public | A | |
| nextjs-opennext | next + @opennextjs/cloudflare | 同上 | `next build && opennextjs-cloudflare build` | （wrangler 配置内置 .open-next） | B | ISR 配 KV/R2 cache override |
| nextjs-plain | next，无 CF adapter | 同上 | 补装 adapter 后同上 | | B | 全静态可加 output:export 走 A |
| nextjs-on-pages | next + @cloudflare/next-on-pages | 同上 | **先迁移到 OpenNext** | | B | 两 adapter 不可共存 |
| nextjs-static-export | next.config `output:'export'` | 同上 | `npm run build` | `out` | A / D | 禁与 OpenNext 混用 |
| worker | wrangler.jsonc/toml（无前端框架主导） | 看脚本 | 有 build 脚本则 `npm run build` | [assets].directory | B | 纯 API 无 assets 也行 |
| hugo / jekyll / mkdocs | 对应配置文件 | - | hugo --minify / jekyll build / mkdocs build | public/_site/site | A | Pages 镜像自带工具链；D 需本地装 |
| monorepo | pnpm-workspace.yaml / workspaces | 按包管理器 | 选定包后同上 | | 按包 | Pages 用 root_dir 指包子目录 |
| express/普通 node server 等 | 无上述标记 | - | - | - | ask-user | CF 无直接对应（Containers 另议），别硬部署 |

## 环境变量速查（Pages deployment_configs.*.env_vars / Workers vars）

- `NODE_VERSION`：覆盖构建镜像 Node 主版本（对照 package.json engines；Vite7/
  Next15+/Astro5 需 ≥20，建议 22）。
- `COMPATIBILITY_DATE`（Workers 用配置文件字段，不是 env）。
- pnpm 仓库：Pages 镜像按 lockfile 自动选 pnpm + corepack；个别老镜像需
  `PACKAGE_MANAGER`/corepack env，报错时看 build log 首行。

## wrangler 版本

本机 npx 已可拉最新（≥4.20 才有完整 Workers Assets；OpenNext 文档建议 4.20+）。
`npx --yes wrangler@latest <cmd>` 是统一调用方式，避免依赖全局安装版本。
