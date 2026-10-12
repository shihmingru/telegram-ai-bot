# Zero-additional-spend operating mode

This configuration is designed to avoid intentionally enabling paid services, but no software change can guarantee permanent $0 operation. Providers can change prices, free quotas, and account terms.

## Cost controls

- Set GEMINI_MODEL to one model verified as free-tier eligible for your exact Gemini API key and region. The bot uses only that model and does not silently try alternatives if it fails or exhausts quota.
- Automatic reverse-image matching is not available in the Telegram bot because no provider has been verified as both reliable and guaranteed free. When the user explicitly asks for reverse-image search, the bot provides Google Lens and Bing Visual Search links for the user to open and upload the image manually. The bot does not forward the image to those sites or call an image-search API. Do not add GOOGLE_CLOUD_VISION_API_KEY while operating under a strict $0 budget.
- No new Render services, databases, disks, workers, or paid schedulers are created.
- The web service remains configured on its existing Render plan. Check the Render dashboard for any changes to plan or billing.
- No arbitrary code execution or paid external research service is added.

## New personal-agent commands

- `/remember TEXT` saves a user-specific memory.
- `/memories` lists saved memories; `/forget ID` deletes one.
- `/task TEXT` adds a task; `/tasks` lists open tasks; `/done ID` completes one.
- `/remind YYYY-MM-DD HH:MM | TEXT` saves a reminder in Taiwan time.
- `/skill french`, `/skill vegetarian cooking`, `/skill drawing`, `/skill buddhist studies`, or `/skill 鈴鼓` selects a coaching mode for the next message.

Memories, tasks and reminders use the existing DATABASE_URL. User records are scoped by Telegram user ID.

## User-defined recurring tasks

The Telegram bot supports these commands in a private chat:

- Describe a request naturally, for example `/schedule Every day at 8am, send me the latest AI headlines`.
- Structured form is also available: `/schedule daily at 08:00 | your request` or `/schedule weekly at 09:30 | your request`.
- Add a timezone when needed, for example `/schedule Every day at 8am [Europe/Paris], send me the latest AI headlines`. Times otherwise default to Taiwan time.
- `/schedules` lists active schedules.
- `/unschedule ID` cancels a schedule.

Requests are stored in the existing PostgreSQL database. The `.github/workflows/scheduled-tasks.yml` GitHub Actions workflow checks for due tasks every 15 minutes and can also be run manually from the Actions tab. It will skip the worker unless the repository Actions variable `ENABLE_RECURRING_TASKS` is exactly `true`. Set this only after confirming that the Gemini API key belongs to a Free Tier project with billing disabled. Scheduled starts can be delayed by GitHub; this is not an exact-time guarantee.

### One-time GitHub Actions setup required

In the repository's Settings → Secrets and variables → Actions, add these repository secrets using the same existing credentials used by the bot:

- `DATABASE_URL`: the existing PostgreSQL connection string.
- `TELEGRAM_TOKEN`: the existing Telegram bot token.
- `GEMINI_API_KEY`: the existing Gemini API key.

Add repository variable `ENABLE_RECURRING_TASKS` set to `true` only after confirming the Gemini project is on the Free Tier with billing disabled. Optionally add `GEMINI_MODEL` with a model available on that Free Tier. If omitted, the worker uses `gemini-2.5-flash-lite`; confirm its availability for the exact project before enabling automation.

Do not paste secrets into chat, source files, workflow YAML, or logs. The bot can save schedules before Actions is configured, but they will not execute automatically until the workflow is enabled, all three secrets are set, and `ENABLE_RECURRING_TASKS=true`. After setup, use Actions → Recurring Telegram tasks → Run workflow to test it. The workflow does not create Render services or databases and does not add paid providers.

The worker supports general user-authored recurring prompts, so the topic does not need to be hard-coded in the source. It is designed for tasks that can return a text result to Telegram, such as summaries, research briefs, study prompts, and reminders. It does not yet perform arbitrary external actions such as booking, purchasing, or changing calendar entries. For requests that appear to need current information, it attempts free Google News RSS retrieval and then Wikipedia search. These sources are best-effort and are not a universal web search engine; the worker must disclose missing live results. Gemini execution still depends on the existing API key's available quota. No paid fallback is attempted.

## Important limitations

- Reminders are checked when the bot receives a Telegram update. Without an always-on scheduler, exact-time delivery is not guaranteed while the bot is idle or suspended. A truly reliable scheduler would require confirming an already-available free service or accepting this limitation.
- Web search first tries public HTML search pages, which can be blocked or rate-limited from cloud-hosted services. If they return no results, the bot now tries the no-key Google News RSS search and Wikipedia's public search API. These fallbacks are free to call but are not guaranteed to be available or to cover every topic. If all providers fail, the bot must say it could not retrieve results rather than inventing them.\n- Free web scraping is best-effort and can be blocked or rate-limited. Retrieved web content must be treated as untrusted data.
- `safe_web.py` rejects private/reserved destinations and revalidates redirects. Application-level DNS validation cannot completely eliminate DNS-rebinding risk without network-level egress controls.
- Gemini availability and free quotas are account-specific and may change. If the configured model is unavailable, the bot intentionally fails rather than attempting a possibly billable model.
- Existing Render free-service sleep/usage rules and the external database provider's plan remain outside this repository's control. Review their dashboards and billing settings regularly.
- This branch has not been deployed to Render. Verify the test workflow and explicitly confirm the chosen Gemini model's free eligibility before merging to `main`.
