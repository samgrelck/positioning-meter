# GitHub Pages Setup

Local git repo is initialized and committed. To publish the dashboard at a public URL:

## Option A: Via GitHub website (no extra tools needed)

1. Go to **https://github.com/new**
2. Repo name: `positioning-meter` (or whatever you prefer)
3. **Public** for free Pages, or Private if you have GitHub Pro
4. Don't initialize with README (we already have one)
5. Click "Create repository"
6. Copy the SSH or HTTPS URL it shows (e.g. `git@github.com:sgrelck/positioning-meter.git`)
7. Run from the project directory:
   ```bash
   cd ~/Documents/AI\ workflows/positioning_meter
   git remote add origin git@github.com:YOUR-USERNAME/positioning-meter.git
   git push -u origin main
   ```
8. **Enable GitHub Pages**:
   - Go to repo Settings → Pages
   - "Build and deployment" → Source: **Deploy from a branch**
   - Branch: `main` / Folder: `/docs`
   - Click Save
9. After ~1 minute, your dashboard will be live at:
   **`https://YOUR-USERNAME.github.io/positioning-meter/`**

## Option B: Via gh CLI (one command after install)

```bash
brew install gh
gh auth login

cd ~/Documents/AI\ workflows/positioning_meter
gh repo create positioning-meter --public --source=. --push --remote=origin

# Enable Pages
gh repo edit --enable-pages --pages-branch=main --pages-path=/docs
```

## Daily refresh after setup

Once configured, run from the project directory to refresh:

```bash
./tools/deploy.sh
```

This re-runs compute → backtest → render → copies to docs/ → commits → pushes. GitHub Pages auto-rebuilds in ~30 seconds.

## Privacy notes

- `.env` is in `.gitignore` — your Polygon key, SEC user agent, etc. won't be pushed
- `data/positioning.db` is gitignored — your local data stays local
- `data/dashboard.html` (raw render) is NOT gitignored but `docs/index.html` (a copy) is what's published
- Only the rendered HTML + source code goes to GitHub
- The HTML embeds aggregated metrics, no personal data

## Cost

- **Public repo**: free (unlimited bandwidth on Pages)
- **Private repo**: requires GitHub Pro ($4/mo) for Pages access

## Custom domain (optional)

If you have a domain, in repo Settings → Pages, set "Custom domain" to e.g. `positioning.yourname.com`. Add a CNAME record at your DNS provider pointing to `YOUR-USERNAME.github.io`.
