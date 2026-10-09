# Reverse image search setup

The Telegram bot can optionally search the web for exact, partial, and visually similar image matches when you explicitly ask it to reverse-search an image. Ordinary image questions continue to use Gemini's image understanding and do not trigger this search.

## Enable the feature

1. In Google Cloud Console, select or create a project and enable the Cloud Vision API.
2. Create an API key for that project. Restrict the key to the Cloud Vision API where possible.
3. In Render, open the `telegram-ai-bot` web service, then Environment, and add `GOOGLE_CLOUD_VISION_API_KEY` with the key value.
4. Save the change and allow Render to redeploy/restart the service.
5. In Telegram, send an image with a clear request such as `Please reverse image search this photo and find the original source.`

## Important notes

- The feature is optional. Without the environment variable, no Vision API request is sent and the bot tells you it is not configured.
- Google Cloud Vision may require billing to be enabled. Check current Cloud Vision pricing and any available free allowance in your Google Cloud account before enabling it. This implementation does not guarantee that use will be free.
- When you explicitly request reverse image search, the image bytes are sent to Google Cloud Vision for Web Detection. Do not use this feature for sensitive images you do not want sent to that service.
- Results are candidate matches. A matching image or page is not by itself proof that it is the original source.
- This is visual web detection, not facial identity recognition.
