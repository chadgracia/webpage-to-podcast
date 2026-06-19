import json
import os
import re
import html
import uuid
import urllib.request
import urllib.parse

import boto3

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-4-6"
S3_BUCKET = "webpage-to-podcast-chadgracia"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def lambda_handler(event, context):
    try:
        params = event.get("queryStringParameters") or {}
        url = params.get("url")

        if not url:
            return _html_response(200, _form_page())

        page_html = _fetch_page(url)
        text = _html_to_text(page_html)
        script = _generate_script(text)
        audio = _synthesize(script)
        audio_url = _upload_and_sign(audio)

        return _html_response(200, _result_page(url, audio_url, script))
    except Exception as exc:  # noqa: BLE001
        return _html_response(500, _error_page(str(exc)))


def _fetch_page(url):
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _html_to_text(page_html):
    # Drop script/style blocks entirely.
    cleaned = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    # Strip remaining tags.
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # Unescape HTML entities.
    cleaned = html.unescape(cleaned)
    # Collapse whitespace.
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:8000]


def _generate_script(text):
    prompt = (
        "Turn the following article into an engaging, conversational spoken "
        "podcast script of about 200 to 250 words. Use plain prose only: no "
        "markdown, no headings, no stage directions, no speaker labels, no "
        "sound cues. Write only the words a text-to-speech engine should read "
        "aloud.\n\nArticle:\n" + text
    )
    payload = json.dumps(
        {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=payload,
        method="POST",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["content"][0]["text"].strip()


def _synthesize(script):
    polly = boto3.client("polly")
    result = polly.synthesize_speech(
        Text=script,
        OutputFormat="mp3",
        VoiceId="Joanna",
        Engine="neural",
    )
    return result["AudioStream"].read()


def _upload_and_sign(audio):
    s3 = boto3.client("s3")
    key = "podcasts/{}.mp3".format(uuid.uuid4())
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=audio,
        ContentType="audio/mpeg",
    )
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": key},
        ExpiresIn=3600,
    )


def _html_response(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "text/html; charset=utf-8"},
        "body": body,
    }


def _form_page():
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Webpage to Podcast</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 640px; margin: 60px auto; padding: 0 20px; }
  h1 { font-size: 1.6rem; }
  input { width: 100%; padding: 12px; font-size: 1rem; box-sizing: border-box; }
  button { margin-top: 12px; padding: 12px 20px; font-size: 1rem; cursor: pointer; }
</style>
</head>
<body>
  <h1>Webpage to Podcast</h1>
  <p>Paste a webpage URL and turn it into a short spoken podcast.</p>
  <form method="get" action="">
    <input type="url" name="url" placeholder="https://example.com/article" required>
    <button type="submit">Make Podcast</button>
  </form>
</body>
</html>"""


def _result_page(source_url, audio_url, script):
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Your Podcast</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 20px; line-height: 1.6; }}
  h1 {{ font-size: 1.6rem; }}
  audio {{ width: 100%; margin: 16px 0; }}
  .script {{ background: #f5f5f5; padding: 16px 20px; border-radius: 8px; white-space: pre-wrap; }}
  a.back {{ display: inline-block; margin-top: 24px; }}
</style>
</head>
<body>
  <h1>Your Podcast</h1>
  <audio controls src="{audio_url}"></audio>
  <p>Source: <a href="{source_url}">{source_url}</a></p>
  <h2>Script</h2>
  <div class="script">{script}</div>
  <a class="back" href="">Make another</a>
</body>
</html>""".format(
        audio_url=html.escape(audio_url, quote=True),
        source_url=html.escape(source_url, quote=True),
        script=html.escape(script),
    )


def _error_page(message):
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Error</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 640px; margin: 60px auto; padding: 0 20px; }}
  .error {{ background: #fdecea; color: #611a15; padding: 16px 20px; border-radius: 8px; white-space: pre-wrap; }}
</style>
</head>
<body>
  <h1>Something went wrong</h1>
  <div class="error">{message}</div>
  <p><a href="">Try again</a></p>
</body>
</html>""".format(message=html.escape(message))
