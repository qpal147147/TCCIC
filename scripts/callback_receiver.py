"""
A local stand-in for a caller's webhook endpoint, for testing job callbacks.

Prints every callback it receives and checks its signature against AUTH_KEY, so
it doubles as a reference for what a real receiver must do: read the raw body,
verify `X-TCCIC-Signature` over "{X-TCCIC-Timestamp}.{raw body}" with
HMAC-SHA256, then answer 2xx. Anything else is retried, then marked failed.

Usage (from the project root):

    python -m scripts.callback_receiver [--port 9000] [--status 200]

Any path is accepted, so the callback_url can be just "http://localhost:9000/";
a real receiver chooses its own path.

To try it against the service:

    1. Set CALLBACK_ALLOW_PRIVATE = True in app/configs/global_settings.py —
       otherwise a localhost callback_url is rejected with 422.
    2. Start this receiver, then start the service.
    3. Submit a job with "callback_url": "http://localhost:9000/".
    4. When the job finishes, the callback is printed here and its row in
       `job_callbacks` reads `delivered`.
    5. Set CALLBACK_ALLOW_PRIVATE back to False when done.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.configs.global_settings import global_settings
from app.services.callback import JOB_ID_HEADER, SIGNATURE_HEADER, TIMESTAMP_HEADER, verify

SECRET = global_settings.AUTH_KEY.get_secret_value()


class Receiver(BaseHTTPRequestHandler):
    status = 200  # set from --status in main()

    def do_POST(self):
        # Verify over the raw bytes: re-serializing the JSON would change them.
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        timestamp = self.headers.get(TIMESTAMP_HEADER, "")
        signature = self.headers.get(SIGNATURE_HEADER, "")
        valid = verify(SECRET, timestamp, body, signature)

        print(f"\n--- POST {self.path}  signature {'OK' if valid else 'INVALID'}  -> answering {self.status}")
        print(f"{JOB_ID_HEADER}: {self.headers.get(JOB_ID_HEADER)}")
        print(json.dumps(json.loads(body), ensure_ascii=False, indent=2), flush=True)

        self.send_response(self.status)
        self.end_headers()

    def log_message(self, *args):
        pass  # the print above says everything worth saying


def main():
    parser = argparse.ArgumentParser(
        prog="python -m scripts.callback_receiver",
        description="Receive TCCIC job callbacks locally and verify their signatures.",
    )
    parser.add_argument("--port", type=int, default=9000, help="port to listen on (default: 9000)")
    parser.add_argument(
        "--status", type=int, default=200,
        help="status code to answer with (default: 200); "
             "500 shows the retries, 404 a rejection that is not retried",
    )
    args = parser.parse_args()

    Receiver.status = args.status
    print(f"Listening on http://localhost:{args.port}/ (answering {args.status}). Ctrl+C to stop.", flush=True)
    try:
        HTTPServer(("0.0.0.0", args.port), Receiver).serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
