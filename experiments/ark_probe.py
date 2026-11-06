"""Call the real Ark endpoint using credentials from the ignored local .env."""

import json
import time
from pathlib import Path

from dotenv import dotenv_values
from openai import APIStatusError, OpenAI

ROOT = Path(__file__).resolve().parents[1]


def main():
    settings = dotenv_values(ROOT / '.env')
    key = settings.get('ARK_API_KEY')
    if not key:
        raise SystemExit('Missing ARK_API_KEY in local .env')
    client = OpenAI(
        api_key=key, base_url=settings['ARK_BASE_URL'], timeout=60, max_retries=0,
    )
    started = time.monotonic()
    report = {'model': settings['ARK_MODEL'], 'api': 'responses', 'live': True}
    try:
        response = client.responses.create(
            model=settings['ARK_MODEL'],
            input=[{'role': 'user', 'content': [
                {'type': 'input_image', 'image_url':
                 'https://ark-project.tos-cn-beijing.volces.com/doc_image/ark_demo_img_1.png'},
                {'type': 'input_text', 'text': '你看见了什么？'},
            ]}],
            max_output_tokens=2048,
        )
        report.update(ok=True, response_status=response.status,
                      text=response.output_text, usage=response.usage.model_dump()
                      if response.usage else None)
    except APIStatusError as exc:
        report.update(ok=False, error_type=type(exc).__name__, status=exc.status_code,
                      message=str(exc).replace(key, '[REDACTED]'))
    except Exception as exc:
        report.update(ok=False, error_type=type(exc).__name__,
                      message=str(exc).replace(key, '[REDACTED]'))
    report['elapsed_seconds'] = round(time.monotonic() - started, 2)
    destination = ROOT / '.local-data/probes/nanobot-probe/ark-responses.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
