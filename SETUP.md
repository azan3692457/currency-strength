# Putting Currency Strength online

GitHub runs the script every hour and publishes the page at
`https://<your-github-username>.github.io/currency-strength/`. The page is public;
the OANDA key stays in a GitHub secret and never appears in the code or the page.

Use your **personal** GitHub account.

## 1. Create the repository

On github.com: **New repository** → name `currency-strength` → **Public** →
leave "Add a README" unchecked → **Create repository**.

## 2. Push these files

From this folder (`~/Desktop/testing/currency-strength-site`):

```bash
git init -b main
git add .
git commit -m "Currency strength page"
git remote add origin https://github.com/<your-github-username>/currency-strength.git
git push -u origin main
```

Check that `.env` is not in the list `git add` picked up (`git status` before committing).

## 3. Add the OANDA key as a secret

Repository → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**. Name: `OANDA_API_KEY`. Value: the key from your `.env` file.

## 4. Turn on Pages

Repository → **Settings** → **Pages** → under "Build and deployment",
**Source: GitHub Actions**.

## 5. Run it once

Repository → **Actions** → **Refresh currency strength** → **Run workflow**.
After about a minute the page is live at the address above. From then on it
refreshes at 5 past every hour, Sunday to Friday.

## Notes

- GitHub can delay scheduled runs by 5–15 minutes when busy.
- GitHub pauses schedules in a repository with no commits for 60 days; it
  emails first, and one click (or any commit) turns it back on.
- To change the page, edit `build_currency_strength.py`, then commit and push.
