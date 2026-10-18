"""
Job callbacks: tell a caller when its job has finished, instead of making it poll.

Every submission that carries a `callback_url` is a subscription (a row in
`job_callbacks`). Once the job reaches a final state, each pending subscription
receives one signed POST whose body is exactly what GET /jobs/{job_id} returns.
Polling remains the fallback; a callback is a convenience, never the only way to
learn the outcome.

Signing: the body is signed with AUTH_KEY — the key the caller already holds —
as HMAC-SHA256 over "{timestamp}.{body}". The timestamp lets a receiver reject a
replayed request. Rotating AUTH_KEY therefore changes what receivers must verify
against.

SSRF: the URL is checked twice. At submission only its shape is checked (no DNS,
so the event loop never blocks); right before every attempt the host is resolved
and every address must be public. The second check is the one that matters — a
hostname can point anywhere, and can be repointed after it was accepted.
"""

import hashlib
import hmac
import ipaddress
import logging
import socket
import threading
import time
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Callable, Optional
from urllib.parse import urlsplit

import httpx

from app.api.schemas.job_schema import JobStatusResponse
from app.services.store import Store
from app.services.store.models import ACTIVE_JOB_STATUSES

logger = logging.getLogger(__name__)

JOB_ID_HEADER = "X-TCCIC-Job-Id"
TIMESTAMP_HEADER = "X-TCCIC-Timestamp"
SIGNATURE_HEADER = "X-TCCIC-Signature"

Resolver = Callable[..., list]


class CallbackURLError(ValueError):
    """A callback URL that must not be called."""


# --- URL checks --------------------------------------------------------------

def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    # An IPv4 address wrapped in IPv6 (::ffff:127.0.0.1) is judged as the IPv4 it is.
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_url_shape(url: str, allow_private: bool = False) -> str:
    """
    What can be checked without DNS: scheme, host, and literal addresses.
    Used at submission. Returns the URL unchanged so it can serve as a validator.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise CallbackURLError("callback_url must be an HTTP or HTTPS URL")
    host = (parts.hostname or "").lower()
    if not host:
        raise CallbackURLError("callback_url has no host")
    if allow_private:
        return url
    if host == "localhost" or host.endswith(".localhost"):
        raise CallbackURLError("callback_url must not point at this machine")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        return url  # a hostname; resolved and checked before every attempt
    if not _is_public(str(literal)):
        raise CallbackURLError("callback_url must not point at a private or reserved address")
    return url


def resolve_public(url: str, allow_private: bool = False, resolver: Resolver = socket.getaddrinfo) -> None:
    """
    Resolve the host and require every address to be public. Used right before
    each attempt. A failed lookup raises socket.gaierror, which is retryable.
    """
    check_url_shape(url, allow_private)
    if allow_private:
        return
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    addresses = {info[4][0] for info in resolver(parts.hostname, port, proto=socket.IPPROTO_TCP)}
    if not addresses or not all(_is_public(address) for address in addresses):
        raise CallbackURLError("callback_url resolves to a private or reserved address")


# --- signing -----------------------------------------------------------------

def sign(secret: str, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + body, hashlib.sha256)
    return f"sha256={digest.hexdigest()}"


def verify(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    """How a receiver checks a callback. Constant-time, so it leaks nothing."""
    return hmac.compare_digest(sign(secret, timestamp, body), signature)


# --- delivery ----------------------------------------------------------------

class CallbackNotifier:
    """
    Sends a finished job's status to every URL that subscribed to it.

    A subscription is a row in `job_callbacks`, created when a submission carries
    a `callback_url`. Its life is: `pending` until the job reaches a final state,
    then exactly one delivery that ends in `delivered` or `failed`. Each delivery
    is a signed POST whose body is the same `JobStatusResponse` that
    GET /jobs/{job_id} returns.

    Deliveries run on a small thread pool, so a slow or dead receiver never holds
    up a crawl worker; callers only ever trigger them through `notify()` and
    `redeliver_pending()`, both of which return immediately. A subscription left
    `pending` by a shutdown is picked up by `redeliver_pending()` at the next
    startup, so nothing is lost across restarts.

    Args:
        store: The metadata store. Read for the job and its subscriptions; each
            subscription's outcome is written back to it.
        secret: Key for the HMAC-SHA256 signature. The service passes AUTH_KEY,
            the key callers already hold to call the API.
        allow_private: Skip the SSRF checks so `localhost` and private addresses
            can be targeted. Development only.
        timeout_s: Timeout for each HTTP attempt, in seconds.
        retry_delays_s: Seconds to wait before each retry. Its length is the
            number of retries, so `(5, 30, 120)` means at most four attempts.
        max_workers: Size of the delivery thread pool.
        client: HTTP client to send with. Defaults to one that does not follow
            redirects. Injectable so tests can use `httpx.MockTransport`.
        sleep: Function used to wait between attempts. Injectable so tests do
            not actually wait.
        resolver: DNS lookup with the signature of `socket.getaddrinfo`.
            Injectable so tests control what a hostname resolves to.
        executor: Where deliveries run. Defaults to a `ThreadPoolExecutor` of
            `max_workers` threads; tests pass one that runs work immediately.
    """

    def __init__(
        self,
        store: Store,
        secret: str,
        *,
        allow_private: bool = False,
        timeout_s: float = 10.0,
        retry_delays_s: tuple[float, ...] = (5.0, 30.0, 120.0),
        max_workers: int = 4,
        client: Optional[httpx.Client] = None,
        sleep: Callable[[float], None] = time.sleep,
        resolver: Resolver = socket.getaddrinfo,
        executor: Optional[Executor] = None,
    ):
        self._store = store
        self._secret = secret
        self._allow_private = allow_private
        self._timeout_s = timeout_s
        self._retry_delays_s = retry_delays_s
        # Redirects are not followed: a public URL must not bounce the request inward.
        self._client = client or httpx.Client(follow_redirects=False)
        self._sleep = sleep
        self._resolver = resolver
        self._executor = executor or ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="callback"
        )
        self._inflight: set[int] = set()
        self._lock = threading.Lock()

    def notify(self, job_id: str) -> None:
        """
        Queue delivery of every pending subscription of a job, if it has finished.

        Safe to call at any moment and any number of times: a job still queued or
        running is left alone (its subscriptions wait for it to end), and a
        subscription already delivered, failed, or being sent is not sent again.
        """
        job = self._store.jobs.get(job_id)
        if job is None or job.status in ACTIVE_JOB_STATUSES:
            return
        for callback in self._store.callbacks.pending_for_job(job_id):
            self._submit(callback.id, callback.job_id, callback.callback_url)

    def redeliver_pending(self) -> int:
        """
        Queue every subscription that a previous run left undelivered.

        Called once at startup, after orphaned jobs have been reconciled, so it
        covers both callbacks cut off by a shutdown and jobs that only just
        became final. Subscriptions of jobs still in flight are not included.
        """
        pending = self._store.callbacks.pending_for_finished_jobs()
        for callback in pending:
            self._submit(callback.id, callback.job_id, callback.callback_url)
        return len(pending)

    def shutdown(self) -> None:
        """
        Stop delivering and release the HTTP client.

        Does not wait for deliveries in progress or queued: whatever is unsent
        stays `pending` and is sent at the next startup.
        """
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._client.close()

    def _submit(self, callback_id: int, job_id: str, url: str) -> None:
        """Hand one subscription to the pool, unless it is already being sent."""
        with self._lock:
            if callback_id in self._inflight:
                return
            self._inflight.add(callback_id)
        self._executor.submit(self._run, callback_id, job_id, url)

    def _run(self, callback_id: int, job_id: str, url: str) -> None:
        """Pool entry point: deliver, log anything unexpected, release the in-flight slot."""
        try:
            self._deliver(callback_id, job_id, url)
        except Exception as e:
            logger.error(f"Callback {callback_id} for job {job_id} crashed: {e}")
        finally:
            with self._lock:
                self._inflight.discard(callback_id)

    def _deliver(self, callback_id: int, job_id: str, url: str) -> None:
        """
        Send one subscription, retrying as needed, and record how it ended.

        Each attempt first resolves the host and refuses any private or reserved
        address, then POSTs the signed job status. Outcomes:

        - 2xx: `delivered`.
        - 4xx other than 408/429: `failed` at once — the receiver refused this
          payload, and sending it again changes nothing.
        - Forbidden address: `failed` at once, without sending.
        - 5xx, 408, 429, timeout, connection or DNS failure: retried after the
          next delay in `retry_delays_s`; `failed` once they are used up.
        """
        # The host only: callers often put a token in the URL, which must not reach the logs.
        target = f"callback {callback_id} for job {job_id} ({urlsplit(url).hostname})"
        job = self._store.jobs.get(job_id)
        if job is None:
            self._store.callbacks.mark(callback_id, "failed")
            return
        body = JobStatusResponse.from_job(job).model_dump_json().encode("utf-8")

        attempts = 1 + len(self._retry_delays_s)
        for attempt in range(attempts):
            if attempt:
                self._sleep(self._retry_delays_s[attempt - 1])

            try:
                resolve_public(url, self._allow_private, self._resolver)
            except CallbackURLError as e:
                # Retrying cannot turn a forbidden address into an allowed one.
                logger.warning(f"Refusing {target}: {e}.")
                self._store.callbacks.mark(callback_id, "failed")
                return
            except OSError as e:
                logger.warning(f"Attempt {attempt + 1}/{attempts} of {target}: lookup failed: {e}.")
                continue

            timestamp = str(int(time.time()))
            headers = {
                "Content-Type": "application/json",
                JOB_ID_HEADER: job_id,
                TIMESTAMP_HEADER: timestamp,
                SIGNATURE_HEADER: sign(self._secret, timestamp, body),
            }
            try:
                response = self._client.post(url, content=body, headers=headers, timeout=self._timeout_s)
            except httpx.HTTPError as e:
                logger.warning(f"Attempt {attempt + 1}/{attempts} of {target} failed: {e}.")
                continue

            if 200 <= response.status_code < 300:
                self._store.callbacks.mark(callback_id, "delivered")
                logger.info(f"Delivered {target}.")
                return
            if 400 <= response.status_code < 500 and response.status_code not in (408, 429):
                # The receiver rejected it; sending the same thing again changes nothing.
                logger.warning(f"Receiver rejected {target} with {response.status_code}; not retrying.")
                self._store.callbacks.mark(callback_id, "failed")
                return
            logger.warning(f"Attempt {attempt + 1}/{attempts} of {target} got {response.status_code}.")

        logger.error(f"Gave up on {target} after {attempts} attempt(s).")
        self._store.callbacks.mark(callback_id, "failed")
