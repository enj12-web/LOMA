# Major Championship Pool — Live Dashboard

Live leaderboard for a fantasy golf pool covering the 4 majors (Masters, PGA Championship, US Open, Open Championship).

## How it works

- **Scoring**: each team picks 6 players. Best 4 of 6 made-cut scores count. If a team has fewer than 4 players make the cut, the team is DQ'd for that major.
- **Data**: pulls from ESPN's public PGA leaderboard JSON every 5 minutes via GitHub Actions.
- **Hosting**: static HTML served from GitHub Pages. No server to maintain, no cost.

## Setup (one-time)

### 1. Create the GitHub repo

```bash
# from this directory
git init
git add .
git commit -m "Initial golf pool dashboard"
git branch -M main
# create a new repo on GitHub (https://github.com/new), then:
git remote add origin git@github.com:<your-username>/<repo-name>.git
git push -u origin main
```

Make sure the repo is **public** — GitHub Pages on private repos requires a paid plan, and public repos get unlimited free Actions minutes.

### 2. Enable GitHub Pages

In the repo on GitHub:
- Settings → Pages
- Source: "Deploy from a branch"
- Branch: `main` / `/ (root)`
- Save

Your dashboard will be live at `https://<your-username>.github.io/<repo-name>/` within a minute or two.

### 3. Enable Actions write permissions

In the repo on GitHub:
- Settings → Actions → General
- Workflow permissions → "Read and write permissions"
- Save

This lets the cron job commit updated standings back to the repo.

### 4. Trigger the first run

- Actions tab → "Update Standings" → "Run workflow" → Run

You should see a new commit appear with `standings.json` populated.

## Updating picks before each major

Edit [picks.json](picks.json):
- `active_event_name`: must match the ESPN event name exactly (e.g. `"PGA Championship"`, `"Masters Tournament"`, `"U.S. Open Championship"`, `"The Open Championship"`).
- `teams`: 6 player names per team. Player names are matched case-insensitively against ESPN's player list, but if a name doesn't match, the dashboard will show a warning banner.

Commit + push the picks change. The cron picks it up within 5 minutes.

## Running the poller locally (testing)

```bash
python3 poller.py
cat standings.json
```

That writes a fresh `standings.json`. Open `index.html` in a browser (or use `python3 -m http.server`) to preview.

## What the dashboard shows

- One card per team, ranked by total (lowest = best).
- 6 players per team — the 4 lowest made-cut scores are highlighted as the "counting" scores.
- Cut players are struck through.
- Players whose names don't match ESPN's list show a `?` and trigger a banner warning.
- DQ teams (fewer than 4 made cut) are dimmed and shown at the bottom.

## Architecture

```
ESPN scoreboard API (5-min cron)
        │
        ▼
GitHub Actions runs poller.py
        │
        ▼
standings.json committed to repo
        │
        ▼
GitHub Pages serves index.html + standings.json
        │
        ▼
Browser fetches standings.json, renders dashboard (auto-refreshes 60s)
```

No server, no database, no auth. Just static files + a scheduled job.
