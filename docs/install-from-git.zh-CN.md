# 从 Git 直接安装 LingTest

发布到 PyPI 之前，或者想用上还没发版的最新提交，可以跳过 PyPI 直接从 GitHub 安装。
PyPI 上的包和仓库代码是同一个 `pyproject.toml`（hatchling 构建），所以两条安装路径
装出来的是同一个 CLI：

```bash
lingtest --version
```

## 一次性安装

推荐用 `uv tool`（隔离环境 + 全局命令，不污染业务项目依赖）：

```bash
uv tool install "lingtest-cli @ git+https://github.com/sunweitest/lingtest-cli.git"
lingtest --version
```

需要 TUI（`lingtest tui`）时带上 extra：

```bash
uv tool install "lingtest-cli[tui] @ git+https://github.com/sunweitest/lingtest-cli.git@main"
```

`pipx` 和 `pip` 同样支持 VCS 地址：

```bash
pipx install "git+https://github.com/sunweitest/lingtest-cli.git"
```

```bash
python -m pip install "lingtest-cli @ git+https://github.com/sunweitest/lingtest-cli.git"
```

已经激活虚拟环境、想把它加进项目依赖：

```bash
uv add --dev "lingtest-cli @ git+https://github.com/sunweitest/lingtest-cli.git"
```

## 钉住某个提交（可复现）

`@` 后面可以跟分支、tag 或完整 commit sha。CI、复现 bug 时用 sha：

```bash
uv tool install "lingtest-cli @ git+https://github.com/sunweitest/lingtest-cli.git@6292c0c1571902f47c5d51a6729a9b81ab51ea5e"
```

分支/tag 也合法：`@main`、`@v0.4.0`。

## 升级与回滚

Git 安装不会随 PyPI 的 `lingtest` 更新，需要显式重装（`uv` 会重新 clone 并解析依赖）：

```bash
uv tool install --force "lingtest-cli @ git+https://github.com/sunweitest/lingtest-cli.git@main"
```

回滚就是把上面的 `@main` 换成上一个可用的 sha 再执行一次。

## 确认自己装的是哪个提交

版本号现在由 Git tag 自动生成（`hatch-vcs`），所以 `lingtest --version` 本身就能看出距离
上个发版有多少提交：

```
0.4.1.dev3+g97b49b9a2        # v0.4.0 之后第 1 个待发布提交 + commit 前缀
0.4.1                         # 正好打在 v0.4.1 tag 上
```

- `dev3` 里 3 是「距离最近 tag 的提交数」，为 0 时不显示；
- `+g<sha>` 是被安装提交的前缀，可直接拿去 `git show <sha>`；
- 有未提交改动时会多一个 `.d20261105` 后缀（dirty）。

要拿到完整 sha（40 位），读安装元数据里的 `direct_url.json`：

```bash
python -c "import importlib.metadata as m; print(m.distribution('lingtest-cli').read_text('direct_url.json'))"
# {"url":"https://github.com/sunweitest/lingtest-cli.git",
#  "vcs_info":{"vcs":"git","commit_id":"6292c0c1571902f47c5d51a6729a9b81ab51ea5e"}}
```

`uv tool` 安装的包也带这个文件，路径在 `~/.local/share/uv/tools/lingtest-cli/` 下。

## 每个提交都可安装是 CI 保证的

`.github/workflows/git-install.yml` 在每次 push / PR 上做三件事：

1. 用 `git+https://github.com/<repo>.git@<本次 sha>` 在一个干净虚拟环境里安装；
2. 跑 `lingtest --version`、`lingtest providers`；
3. 用 `examples/openapi.yaml` 跑一次 `lingtest generate` + `lingtest run` 冒烟。

所以只要 CI 绿，这个提交就能被任何人从 Git 装上——不需要先发版到 PyPI。

## 什么时候还需要发 PyPI

- 想让不用 Git 的用户 `pip install lingtest-cli` 拿到新版本；
- 需要版本号语义（`0.4.1`、`0.5.0`）给下游做依赖约束；
- 需要 wheel/sdist 被镜像站缓存。

其余场景（内部试用、Agent 部署、CI 里固定提交）直接从 Git 装更省事。

## 常见问题

**`ERROR: Could not find a version that satisfies the requirement lingtest-cli`**
VCS 安装必须带 `name @` 前缀或直接写 `git+https://...`，不能只写包名。
正确：`pip install "lingtest-cli @ git+https://github.com/sunweitest/lingtest-cli.git"`。

**装完 `lingtest: command not found`**
`pip install` 装进了某个虚拟环境，需要先激活它；想要全局命令用 `uv tool install` 或 `pipx`。

**`uv tool install` 后升级没反应**
Git 源的升级要重装：加 `--force`。

**私有仓库**
把 URL 换成 SSH：`git+ssh://git@github.com/<owner>/<repo>.git`，并确保运行安装的用户有对应
deploy key。
