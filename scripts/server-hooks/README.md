# Server-side enforcement — keep `docs/` and `CLAUDE.md` off public `main`

Local hooks (`scripts/hooks/pre-push`) only protect the machine that installed
them. These server-side rules enforce the same invariant for **everyone**, on
both remotes. The two hosts need different mechanisms:

| Host | In-house docs allowed anywhere? | Mechanism |
|------|--------------------------------|-----------|
| github.com (`Stratus5/GraphRAG`) | No — never, on any branch | Push ruleset (repo-wide path restriction) + CI check |
| code.stratus5.com (`oss/graphrag`) | Yes, on `internal` only | Branch-aware `pre-receive` server hook |

---

## 1. GitHub — push ruleset (preventive, rejects the push)

A repo-wide "restrict file paths" push rule. Since GitHub has no `internal`
branch, blocking `docs/**` and `CLAUDE.md` everywhere is exactly right.

### Web UI
Repo → **Settings → Rules → Rulesets → New ruleset → New push ruleset**
- Enforcement: **Active**
- Add rule: **Restrict file paths** → add `docs/**` and `CLAUDE.md`
- Save.

### API (needs a token with repo *Administration: write*)
```bash
export GITHUB_TOKEN=...   # PAT with admin on Stratus5/GraphRAG
curl -sS -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/Stratus5/GraphRAG/rulesets \
  -d '{
    "name": "no-inhouse-docs",
    "target": "push",
    "enforcement": "active",
    "rules": [
      { "type": "file_path_restriction",
        "parameters": { "restricted_file_paths": ["docs/**", "CLAUDE.md"] } }
    ]
  }'
```
With the GitHub CLI once installed: `gh api --method POST repos/Stratus5/GraphRAG/rulesets --input ruleset.json`.

> Note: push rulesets with file-path restrictions are available for public
> repos and for org repos on Team/Enterprise. If your plan hides the option,
> rely on the CI check below plus branch protection.

## 2. GitHub — CI check (detective, already in the repo)

`.github/workflows/guard-inhouse-docs.yml` fails whenever `docs/` or
`CLAUDE.md` is tracked. It runs *after* a push, so it's a backstop, not
prevention. To make it bite on PRs:
Repo → **Settings → Branches → Add branch protection rule** for `main` →
**Require status checks to pass** → select **no-inhouse-docs**. Also enable
**Do not allow bypassing** and restrict who can push to `main`.

---

## 3. code.stratus5.com (GitLab) — branch-aware `pre-receive` hook

GitLab's built-in push rules (Premium) restrict file names **repo-wide**, which
would wrongly block `internal` too. So we use a server hook that checks the
branch. Script: `gitlab-pre-receive` (in this directory).

### Option A — global server hook (Omnibus GitLab, applies to all repos)
```bash
# On the GitLab server, as root:
grep custom_hooks_dir /etc/gitlab/gitlab.rb        # find/confirm the dir, e.g.:
# gitaly['configuration'] = { hooks: { custom_hooks_dir: "/var/opt/gitlab/gitaly/custom_hooks" } }

DIR=/var/opt/gitlab/gitaly/custom_hooks/pre-receive.d
mkdir -p "$DIR"
cp gitlab-pre-receive "$DIR/no-inhouse-docs"
chmod +x "$DIR/no-inhouse-docs"
chown git:git "$DIR/no-inhouse-docs"    # must be runnable by the git user
```
If `custom_hooks_dir` isn't set, add it under `gitaly['configuration']` in
`/etc/gitlab/gitlab.rb`, then `gitlab-ctl reconfigure`.

### Option B — per-project hook (this repo only)
Find the repo's on-disk path (Admin → Overview → Projects → *graphrag* →
"Gitaly relative path", under `@hashed/...`), then:
```bash
DIR=/var/opt/gitlab/git-data/repositories/@hashed/xx/yy/<hash>.git/custom_hooks
mkdir -p "$DIR"
cp gitlab-pre-receive "$DIR/pre-receive"
chmod +x "$DIR/pre-receive"
chown git:git "$DIR/pre-receive"
```

### Verify
From a clone, try to sneak a doc onto main and confirm rejection:
```bash
git checkout main && git checkout internal -- CLAUDE.md && git add CLAUDE.md
git commit -m "should be rejected" && git push origin main   # expect GL-REJECT
git reset --hard @{u}   # clean up
```
