"""
Tests for job callbacks: who is told, what they receive, and when a delivery is
given up on.

HTTP, DNS, sleeping and the thread pool are all stubbed, so these run offline and
synchronously. Wiring into the API is covered in test_job_api.py.

Using: pytest tests/test_callback.py
"""

import json
import socket

import httpx
import pytest
from sqlalchemy import select

from app.api.schemas.job_schema import JobStatusResponse
from app.services.callback import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    CallbackNotifier,
    CallbackURLError,
    check_url_shape,
    resolve_public,
    sign,
    verify,
)
from app.services.store import JobCallback, Store

SECRET = "test-auth-key"
HOOK = "https://hooks.example.com/tccic"
PUBLIC_IP = "93.184.216.34"


class ImmediateExecutor:
    """Runs submitted work at once, so a test can assert right after notify()."""

    def __init__(self):
        self.submitted = 0

    def submit(self, fn, *args):
        self.submitted += 1
        fn(*args)

    def shutdown(self, wait=True, cancel_futures=False):
        pass


def resolver_for(*addresses):
    def resolve(host, port, proto=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, proto, "", (address, port)) for address in addresses]
    return resolve


def failing_resolver(host, port, proto=0):
    raise socket.gaierror("temporary failure in name resolution")


class Receiver:
    """Answers each request with the next status code and remembers what arrived."""

    def __init__(self, *statuses: int):
        self.statuses = list(statuses) or [200]
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return httpx.Response(status)


@pytest.fixture
def store():
    s = Store(":memory:")
    s.create_all()
    yield s
    s.close()


def build(store, receiver=None, resolver=None, **kwargs):
    receiver = receiver or Receiver()
    sleeps: list[float] = []
    notifier = CallbackNotifier(
        store,
        SECRET,
        client=httpx.Client(transport=httpx.MockTransport(receiver)),
        sleep=sleeps.append,
        resolver=resolver or resolver_for(PUBLIC_IP),
        executor=ImmediateExecutor(),
        **kwargs,
    )
    return notifier, receiver, sleeps


def finished_job(store, job_id="job-1", url=HOOK):
    store.jobs.create(job_id, "card_list", "taishin", "https://bank.test/list")
    callback = store.callbacks.subscribe(job_id, url) if url else None
    store.jobs.mark_completed(job_id, stats={"cards": 3})
    return callback


def status_of(store, callback):
    with store.session_factory() as session:
        return session.get(JobCallback, callback.id).status


# --- signing -----------------------------------------------------------------

def test_a_signature_verifies_and_a_tampered_body_does_not():
    body = b'{"status":"completed"}'
    signature = sign(SECRET, "1700000000", body)

    assert verify(SECRET, "1700000000", body, signature)
    assert not verify(SECRET, "1700000000", b'{"status":"error"}', signature)
    assert not verify(SECRET, "1700000001", body, signature)  # the timestamp is signed too
    assert not verify("another-key", "1700000000", body, signature)


def test_what_is_sent_can_be_verified_by_the_receiver(store):
    finished_job(store)
    notifier, receiver, _ = build(store)

    notifier.notify("job-1")

    request = receiver.requests[0]
    assert verify(SECRET, request.headers[TIMESTAMP_HEADER], request.content, request.headers[SIGNATURE_HEADER])


# --- URL checks --------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "ftp://example.com/hook",
    "http://localhost/hook",
    "http://api.localhost/hook",
    "http://127.0.0.1/hook",
    "http://192.168.1.10/hook",
    "http://169.254.169.254/latest",
    "http://[::1]/hook",
    "http://[::ffff:10.0.0.1]/hook",
])
def test_unsafe_urls_are_rejected_at_submission(url):
    with pytest.raises(CallbackURLError):
        check_url_shape(url)


def test_a_hostname_passes_the_shape_check_and_is_resolved_later():
    assert check_url_shape("https://internal.corp/hook") == "https://internal.corp/hook"


def test_a_hostname_resolving_inward_is_rejected_before_sending():
    with pytest.raises(CallbackURLError):
        resolve_public("https://internal.corp/hook", resolver=resolver_for(PUBLIC_IP, "10.1.2.3"))


def test_private_targets_are_allowed_when_switched_on():
    check_url_shape("http://localhost:9000/hook", allow_private=True)
    resolve_public("http://localhost:9000/hook", allow_private=True, resolver=resolver_for("127.0.0.1"))


# --- delivery ----------------------------------------------------------------

def test_a_2xx_marks_the_callback_delivered(store):
    callback = finished_job(store)
    notifier, receiver, sleeps = build(store, Receiver(204))

    notifier.notify("job-1")

    assert len(receiver.requests) == 1
    assert sleeps == []
    assert store.callbacks.pending_for_job("job-1") == []
    assert store.callbacks.pending_for_finished_jobs() == []
    assert status_of(store, callback) == "delivered"


def test_the_payload_is_what_polling_the_job_returns(store):
    """A callback and GET /jobs/{job_id} must never disagree."""
    finished_job(store)
    notifier, receiver, _ = build(store)

    notifier.notify("job-1")

    expected = JobStatusResponse.from_job(store.jobs.get("job-1")).model_dump(mode="json")
    assert json.loads(receiver.requests[0].content) == expected
    assert receiver.requests[0].headers["X-TCCIC-Job-Id"] == "job-1"


def test_a_server_error_is_retried_then_given_up_on(store):
    callback = finished_job(store)
    notifier, receiver, sleeps = build(store, Receiver(500), retry_delays_s=(5.0, 30.0, 120.0))

    notifier.notify("job-1")

    assert len(receiver.requests) == 4  # the first attempt plus three retries
    assert sleeps == [5.0, 30.0, 120.0]
    assert status_of(store, callback) == "failed"


def test_a_retry_that_succeeds_is_delivered(store):
    callback = finished_job(store)
    notifier, receiver, sleeps = build(store, Receiver(503, 429, 200))

    notifier.notify("job-1")

    assert len(receiver.requests) == 3
    assert sleeps == [5.0, 30.0]
    assert status_of(store, callback) == "delivered"


def test_a_rejection_is_not_retried(store):
    """A 4xx means the receiver refused this payload; sending it again changes nothing."""
    callback = finished_job(store)
    notifier, receiver, sleeps = build(store, Receiver(404))

    notifier.notify("job-1")

    assert len(receiver.requests) == 1
    assert sleeps == []
    assert status_of(store, callback) == "failed"


def test_a_forbidden_address_is_refused_without_sending(store):
    callback = finished_job(store, url="https://internal.corp/hook")
    notifier, receiver, sleeps = build(store, resolver=resolver_for("10.1.2.3"))

    notifier.notify("job-1")

    assert receiver.requests == []
    assert sleeps == []  # no retry: the address will not become allowed
    assert status_of(store, callback) == "failed"


def test_a_failed_lookup_is_retried(store):
    callback = finished_job(store)
    notifier, receiver, sleeps = build(store, resolver=failing_resolver, retry_delays_s=(1.0,))

    notifier.notify("job-1")

    assert receiver.requests == []
    assert sleeps == [1.0]
    assert status_of(store, callback) == "failed"


# --- who is told, and when ---------------------------------------------------

def test_a_job_without_a_callback_sends_nothing(store):
    finished_job(store, url=None)
    notifier, receiver, _ = build(store)

    notifier.notify("job-1")

    assert receiver.requests == []


def test_a_job_still_in_flight_sends_nothing(store):
    store.jobs.create("job-1", "card_list", "taishin", "https://bank.test/list")
    store.callbacks.subscribe("job-1", HOOK)
    notifier, receiver, _ = build(store)

    notifier.notify("job-1")
    store.jobs.mark_running("job-1")
    notifier.notify("job-1")

    assert receiver.requests == []
    assert len(store.callbacks.pending_for_job("job-1")) == 1


def test_a_delivered_callback_is_not_sent_again(store):
    finished_job(store)
    notifier, receiver, _ = build(store)

    notifier.notify("job-1")
    notifier.notify("job-1")

    assert len(receiver.requests) == 1


def test_every_subscription_is_told_and_one_failure_spares_the_others(store):
    finished_job(store, url=f"{HOOK}/a")
    store.callbacks.subscribe("job-1", f"{HOOK}/b")
    notifier, receiver, _ = build(store, Receiver(410, 200))

    notifier.notify("job-1")

    assert [r.url.path for r in receiver.requests] == ["/tccic/a", "/tccic/b"]
    assert store.callbacks.pending_for_job("job-1") == []
    statuses = sorted(status_of(store, c) for c in _all_callbacks(store, "job-1"))
    assert statuses == ["delivered", "failed"]


def test_startup_sends_what_a_previous_run_left_behind(store):
    finished_job(store, "done")
    store.jobs.create("queued", "card_list", "taishin", "https://bank.test/list")
    store.callbacks.subscribe("queued", HOOK)
    notifier, receiver, _ = build(store)

    redelivered = notifier.redeliver_pending()

    assert redelivered == 1
    assert [r.headers["X-TCCIC-Job-Id"] for r in receiver.requests] == ["done"]


def test_a_callback_already_being_sent_is_not_submitted_twice(store):
    finished_job(store)
    notifier, _, _ = build(store)
    notifier._inflight.add(store.callbacks.pending_for_job("job-1")[0].id)

    notifier.notify("job-1")

    assert notifier._executor.submitted == 0


def _all_callbacks(store, job_id):
    with store.session_factory() as session:
        return list(session.scalars(select(JobCallback).where(JobCallback.job_id == job_id)))
