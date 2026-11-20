# Publishing to GitHub over SSH

1. **Create an SSH key** (skip if you already have one for GitHub):
   ```bash
   ssh-keygen -t ed25519 -C "you@example.com" -f ~/.ssh/id_ed25519_github
   eval "$(ssh-agent -s)" && ssh-add ~/.ssh/id_ed25519_github
   cat ~/.ssh/id_ed25519_github.pub      # copy this
   ```
2. GitHub → **Settings → SSH and GPG keys → New SSH key**, paste the public key.
3. Test: `ssh -T git@github.com` should greet you by user name.
4. On GitHub create an **empty** repository named `iuk-browser` (no README/license/.gitignore).
5. Push:
   ```bash
   cd iuk-browser
   scripts/publish-to-github.sh git@github.com:<your-user>/iuk-browser.git
   ```
   or by hand: `git init -b main && git add -A && git commit -m "Initial import" && git remote add origin git@github.com:<your-user>/iuk-browser.git && git push -u origin main`
6. Set `repo_url` in `branding/brand.json` to your real repository URL, run `python3 branding/generate.py` and `python3 branding/apply_to_source.py <firefox-src>` again later so the About and installer links point to it.
7. Add `branding/generated/social-preview.png` as the repository social preview (Settings → General).

## Releases

```bash
git tag v0.1.0 && git push origin v0.1.0
```
Attach only what you are allowed to redistribute: the extension `.zip`/`.xpi`, and **binaries from the source build** (unofficial branding). Do not attach the Mozilla-branded quick bundles from the *Bundles (personal)* workflow.
