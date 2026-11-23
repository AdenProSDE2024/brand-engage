# brand-engage

A weekday digest that tells Aden Yu what to reply to on X and LinkedIn, and drafts the words. He posts everything himself.

Aden does go-to-market at Subliminal Labs. Subliminal installs a recorder that watches how a back-office team actually works, finds the workflows an AI could take over, then builds and tests those automations in a shadow environment before any rollout. It is paid from a share of the savings. Beachhead buyers are PE firms, their operating partners and portfolio companies, plus desk-heavy operators (BPOs, insurance, lending, accounting, staffing, and similar).

The personal account is [@AdenYCantU](https://x.com/AdenYCantU). The company account is [@Subliminal_Labs](https://x.com/Subliminal_Labs). Drafts are for the personal account.

## What this never does

- It never posts, replies, likes, follows, reposts, quotes, or sends a DM on X or LinkedIn.
- It never calls a write endpoint. The X client can only `GET https://api.x.com/2/tweets/search/recent`. There is no pagination.
- It never scrapes LinkedIn. LinkedIn posts enter only when Aden pastes them.
- It never says Subliminal builds or deploys automations "for you", and the draft checker rejects that consultancy voice.
- It never puts secrets in the repo. Tokens stay in the environment.

X's automation rules forbid unsolicited automated replies, including replies driven by keyword search. LinkedIn forbids automation. Those rules are why the output is a draft.

## Set up (about 5 minutes)

You need a machine with Python 3.11+ only if you want to dry-run locally. The scheduled run is GitHub Actions.

1. **Add repository secrets** (Settings → Secrets and variables → Actions → Secrets):
   - `X_BEARER_TOKEN`: app-only bearer token from the X developer console. Recent search is a read. Do not create a user token, and do not grant write scopes. A token that happens to have write scopes still cannot write from this code, because the write calls do not exist.
   - `LLM_API_KEY`: key for the model in `config/settings.yaml`.
   - `SLACK_WEBHOOK_URL`: incoming webhook for a **private channel only you use**. This is how the digest reaches your phone. Without it, a live Actions run fails on purpose rather than printing drafts into a public log.

2. **Optional variables** (same page, Variables), if you do not want a commit to change the model:
   - `LLM_PROVIDER`: `openai` or `anthropic`
   - `LLM_MODEL`
   - `LLM_BASE_URL`: any OpenAI-compatible host, such as OpenRouter or Groq. Ignored for the default Anthropic URL.

3. **Edit `config/targets.yaml`.** Every seeded X handle is `confirmed: false`. That flag is a reminder, not a switch: enabled handles are still searched. Replace anyone you do not want. Handles that start with `TODO` are skipped. Put real PE operating partners and desk-heavy operators in those rows. LinkedIn profile URLs are stubs. Replace them too. `topic_terms` is the list of subjects a reply is allowed to be about. A post that matches none of them is dropped.

4. **Set `your_follower_count`** in `config/settings.yaml` to your real count. An author has to be at least 10x that, and at least 5,000 followers. The tool does not look the count up.

5. **Replace `notes/example.md`** with what you are working on. A sentence or two is enough. Do not put customer names or deal details in `notes/`. This repo is public. Original posts are drawn from these files.

6. **Paste LinkedIn posts** into `linkedin_inbox.md` using the block at the top of that file. A url containing `EXAMPLE` or `TODO` is ignored. Delete a block after it has been digested if you do not want the same comment again tomorrow.

7. **Merge to `main`.** The schedule runs from the default branch only. Weekdays at 14:30 UTC, which is 6:30am Pacific Standard Time and 7:30am Pacific Daylight Time. GitHub's cron has no time zone, so summer runs an hour later. You can also open the Actions tab and run **Daily brand engage** by hand. Check **dry run** to use fixture data and skip every network call.

8. **Post the drafts yourself**, from @AdenYCantU. Do not paste the same text to @Subliminal_Labs. Then fill `used` and `result` in `log.csv`.

Local dry run, with no keys:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m brand_engage --dry-run
pytest
```

A live local run uses the same secrets as environment variables. The digest is written to `digests/YYYY-MM-DD.md`, which git ignores.

```bash
export X_BEARER_TOKEN=...
export LLM_API_KEY=...
export SLACK_WEBHOOK_URL=...   # optional locally
python -m brand_engage
```

## What a morning looks like

The digest has 6 to 8 items when the day is rich, best reply window first. A thin day stays thin. It does not pad the list.

Each item has the link, who the author is and why they matter, why the window is open now, the post, and a draft. Drafts are short, specific, and free of empty praise. Most of them do not mention Subliminal. After the items, a short list of LinkedIn profiles to open yourself.

X candidates have to be under about 6 hours old, from an account far bigger than yours, in English, not a reply or repost, and about a subject in `topic_terms`. Ranking prefers a young post whose engagement is rising, and pushes down a thread that is already crowded.

`log.csv` columns: `date, platform, kind, url, author, draft, used, result, notes`. You type `used` (`yes` or `no`) and a short `result` (`3 likes`, `a follow`, `ignored`). A later run will not overwrite a row you have marked. There is no auto-tuning.

## Model

`config/settings.yaml` selects the provider.

- `openai` posts to `{base_url}/chat/completions`. The default base is `https://api.openai.com/v1`. Point `base_url` at any compatible host.
- `anthropic` posts to `https://api.anthropic.com/v1/messages`.

The LLM client refuses hosts on X, Twitter, LinkedIn, and Slack. If a draft breaks the claims rule, it gets one rewrite. If the rewrite still fails, the digest shows the draft with an "Edit before posting" note.

## X cost

Recent search is available to all developers on X's pay-per-use plan. As of November 2026, public pricing pages bill about **$0.005 per post returned** (a user read is about $0.010). Confirm the current price in the developer console before you turn the schedule on. Prices move.

The default run is 4 requests of 10 posts, about $0.20 a weekday, plus a small LLM charge. The code will not send more than 8 search requests, and it will not follow `next_token`. `start_time` is set to the freshness window so older posts are not billed. Raise `max_results_per_request` (10 to 100) if one loud account fills the page. Each extra post costs the same $0.005.

## Privacy

`commit_digest` defaults to **false**.

- The digest is not committed.
- On GitHub Actions it is not printed and not uploaded as an artifact. Both the log and the artifacts of a public repo are world-readable.
- It is posted to `SLACK_WEBHOOK_URL` if that secret is set. If the secret is missing, the Actions run fails instead of leaking the drafts.

Set `commit_digest: true` only if you are willing for the digest and `log.csv` to be public. The workflow's token cannot push unless that flag is true. A protected `main` branch can still reject the push. Leave the flag off unless you have a reason.

`config/targets.yaml` and `notes/` **are** public. Treat them that way.

## Decisions and limits

A few things in the brief do not survive contact with the platforms. This is what the code does instead.

- **Not every HTTP call can be a GET.** The LLM API and the Slack incoming webhook are POST. They live in `draft.py` and `slack_delivery.py`. Both refuse X, Twitter, and LinkedIn hosts. Tests scan the package so a write path (`/likes`, `/retweets`, `/following`, DMs, LinkedIn, full-archive search) cannot land quietly. The X client has no POST method and refuses redirects.
- **Slack-only is not private if the Actions log prints the digest.** Public repo logs and artifacts are public. The default run sends Slack and does not print or upload the body.
- **`confirmed: false` does not disable an account.** If it did, the seed list would never run. TODO handles and `enabled: false` are the off switches.
- **Follower count is a setting, not a live lookup.** A user read costs money and the number barely moves. Set `your_follower_count`.
- **Replies come before your own posts.** A reply window closes while you are still on the train. A new post can wait.
- **The list does not invent items to hit 8.** If the morning is quiet, the digest says so.
- **One post per author** until the day would otherwise be short. A loud account can still fill a 10-post page. `start_time` plus the per-author cap is the mitigation, and `max_results_per_request` is the knob.
- **LinkedIn "check these profiles" cannot see their feed.** It is a reminder. Comments exist only for pastes.
- **Drafts are not cross-posted.** The same text on @AdenYCantU and @Subliminal_Labs trips X's rule against substantially similar posts across accounts.
- **The schedule drifts one hour in summer.** 14:30 UTC is the weekday 6:30am PST slot. There is not a second workflow chasing daylight time.

## Tests

`pytest` covers ranking, the follower and age filters, query size, the LinkedIn paste format, the draft claims checker, the log, and a dry run from fixtures. A source scan fails if anything but the LLM and Slack modules issues a POST, or if a social write path appears. CI runs the same suite on every push and pull request.
