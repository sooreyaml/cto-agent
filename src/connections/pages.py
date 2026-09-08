import html

from fastapi.responses import HTMLResponse


def oauth_page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{html.escape(title)}</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 36rem; margin: 3rem auto; line-height: 1.5;">
  <h1>{html.escape(title)}</h1>
  <p>{body}</p>
</body>
</html>
""",
        status_code=status,
    )
