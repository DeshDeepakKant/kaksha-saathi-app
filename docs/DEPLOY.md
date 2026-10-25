# Deploying the demo (freeze for evaluation)

The evaluation window expects a reachable link, frozen at submission. Two supported paths.

## A. One small VM + Docker (recommended)

```bash
git clone <repo> && cd Kaksha_Saathi
cp backend/.env.example backend/.env    # fill keys
docker compose up -d --build            # API + Postgres, serves /, /teacher/, /parent/
```

Put a TLS reverse proxy in front (Caddy is two lines):

```
demo.example.org {
    reverse_proxy localhost:8000
}
```

Then rebuild the web apps against the public origin so they call the right API:

```bash
cd apps/teacher && flutter build web --release --base-href /teacher/ --dart-define=API_BASE=https://demo.example.org \
  && rsync -a --delete build/web/ ../../deploy/web/teacher/
cd ../parent && flutter build web --release --base-href /parent/ --dart-define=API_BASE=https://demo.example.org \
  && rsync -a --delete build/web/ ../../deploy/web/parent/
```

## B. Single container, SQLite (fastest)

```bash
docker build -f backend/Dockerfile -t kaksha .
docker run -p 8000:8000 -e JWT_SECRET=... -e ANTHROPIC_API_KEY=... \
  -v $(pwd)/data:/data -e DATABASE_URL=sqlite:////data/kaksha.db kaksha
```

## Checklist before freezing

- [ ] `/healthz` and `/readyz` green; `/teacher/` and `/parent/` load on a phone-sized viewport
- [ ] Demo logins work (teacher `DEMO`/`1234`; parent `DEMO`/12/`9876500000`/`0000`)
- [ ] `python evals/run_extraction.py --mode live` numbers recorded in `docs/EVAL_RESULTS.md`
- [ ] No `.env`, keys or real child data in the repo (`git status`, `git log -p | grep -i key`)
- [ ] APKs built and uploadable (see `apps/*/README.md`)
- [ ] Backup demo video recorded
- [ ] No commits after the deadline — tag the frozen commit: `git tag submission-2026-11-01`
