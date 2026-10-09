# Zero-additional-spend operating mode

This configuration is designed to avoid intentionally enabling paid services, but no software change can guarantee permanent $0 operation. Providers can change prices, free quotas, and account terms.

## Cost controls

- Set GEMINI_MODEL to one model verified as free-tier eligible for your exact Gemini API key and region. The bot uses only that model and does not silently try alternatives if it fails or exhausts quota.
- Reverse-image search via Google Cloud Vision is disabled in the Telegram processing path. Do not add GOOGLE_CLOUD_VISION_API_KEY while operating under a strict $0 budget.
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

## Important limitations

- Reminders are checked when the bot receives a Telegram update. Without an always-on scheduler, exact-time delivery is not guaranteed while the bot is idle or suspended. A truly reliable scheduler would require confirming an already-available free service or accepting this limitation.
- Free web scraping is best-effort and can be blocked or rate-limited. Retrieved web content must be treated as untrusted data.
- `safe_web.py` rejects private/reserved destinations and revalidates redirects. Application-level DNS validation cannot completely eliminate DNS-rebinding risk without network-level egress controls.
- Gemini availability and free quotas are account-specific and may change. If the configured model is unavailable, the bot intentionally fails rather than attempting a possibly billable model.
- Existing Render free-service sleep/usage rules and the external database provider's plan remain outside this repository's control. Review their dashboards and billing settings regularly.
- This branch has not been deployed to Render. Verify the test workflow and explicitly confirm the chosen Gemini model's free eligibility before merging to `main`.
