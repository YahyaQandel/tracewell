"""
Parses TW-1's CLI upload parts into internal dataclasses, ready to persist.

Wire contract (see design.md for the full verification against cli/src/):
- `report` is `ParsedRun` JSON (`{"tests": [...]}`) — already-parsed by the
  CLI, not raw Playwright `suites[]`.
- `manifest` is the only mechanism correlating an uploaded attachment part
  to a specific test's specific retry attempt.

Deliberately uses `retries[].attachments` (via manifest), never the
top-level `ParsedTest.attachments` field — that field mirrors only the
last attempt (see resolveAttachments.ts), and walking it server-side would
silently drop every earlier attempt's attachments.
"""
from dataclasses import dataclass, field

ATTEMPT_STATUSES = {'passed', 'failed', 'timedOut', 'skipped', 'interrupted'}
TEST_OUTCOMES = {'passed', 'failed', 'skipped', 'flaky'}


class ParseError(Exception):
    """Raised for any malformed/invalid upload input. Callers map this to HTTP 400."""


@dataclass
class ParsedAttachment:
    part_name: str
    name: str
    content_type: str


@dataclass
class ParsedAttempt:
    retry_index: int
    status: str
    duration_ms: int
    attachments: list[ParsedAttachment] = field(default_factory=list)
    # Raw AttachmentRef[] from this retry's own "attachments" field, kept
    # only so _apply_manifest_entry can look up a declared contentType by
    # name - not part of this module's public contract with views.py.
    _raw_attachments_by_name: dict = field(default_factory=dict, repr=False)


@dataclass
class ParsedTestCase:
    test_id: str
    title: str
    outcome: str
    attempts: list[ParsedAttempt] = field(default_factory=list)


@dataclass
class ParsedUpload:
    tests: list[ParsedTestCase]


def parse_upload(report, manifest) -> ParsedUpload:
    """
    `report`: already JSON-decoded `ParsedRun` object (`{"tests": [...]}`).
    `manifest`: already JSON-decoded `ManifestEntry[]` list.
    Raises ParseError for any structural problem. Pure — no I/O, no DB.
    """
    if not isinstance(report, dict):
        raise ParseError('report must be a JSON object')
    if 'tests' not in report:
        raise ParseError('report is missing required "tests" array')
    raw_tests = report['tests']
    if not isinstance(raw_tests, list):
        raise ParseError('report "tests" must be an array')

    tests = [_parse_test(t) for t in raw_tests]
    tests_by_id = {t.test_id: t for t in tests}

    if not isinstance(manifest, list):
        raise ParseError('manifest must be an array')

    for entry in manifest:
        _apply_manifest_entry(entry, tests_by_id)

    return ParsedUpload(tests=tests)


def _parse_test(raw) -> ParsedTestCase:
    if not isinstance(raw, dict):
        raise ParseError('test entry must be an object')
    test_id = raw.get('id')
    title = raw.get('title')
    outcome = raw.get('outcome')
    if not isinstance(test_id, str):
        raise ParseError('test "id" must be a string')
    if not isinstance(title, str):
        raise ParseError('test "title" must be a string')
    if outcome not in TEST_OUTCOMES:
        raise ParseError(f'unrecognized test outcome: {outcome!r}')

    raw_retries = raw.get('retries')
    if not isinstance(raw_retries, list):
        raise ParseError('test "retries" must be an array')

    attempts = [_parse_attempt(i, r) for i, r in enumerate(raw_retries)]
    return ParsedTestCase(test_id=test_id, title=title, outcome=outcome, attempts=attempts)


def _parse_attempt(retry_index, raw) -> ParsedAttempt:
    if not isinstance(raw, dict):
        raise ParseError('retry entry must be an object')
    status = raw.get('status')
    duration = raw.get('duration')
    if status not in ATTEMPT_STATUSES:
        raise ParseError(f'unrecognized attempt status: {status!r}')
    if not isinstance(duration, (int, float)):
        raise ParseError('retry "duration" must be a number')

    raw_attachments = raw.get('attachments') or []
    raw_by_name = {}
    if isinstance(raw_attachments, list):
        for raw_attachment in raw_attachments:
            if isinstance(raw_attachment, dict) and isinstance(raw_attachment.get('name'), str):
                raw_by_name[raw_attachment['name']] = raw_attachment.get('contentType')

    return ParsedAttempt(
        retry_index=retry_index,
        status=status,
        duration_ms=int(duration),
        attachments=[],
        _raw_attachments_by_name=raw_by_name,
    )


def _apply_manifest_entry(entry, tests_by_id):
    if not isinstance(entry, dict):
        raise ParseError('manifest entry must be an object')
    test_id = entry.get('testId')
    attachment_name = entry.get('attachmentName')
    part_name = entry.get('partName')
    retry_index = entry.get('retryIndex')

    test = tests_by_id.get(test_id)
    if test is None:
        raise ParseError(f'manifest entry references unknown testId: {test_id!r}')
    if not isinstance(retry_index, int) or retry_index < 0 or retry_index >= len(test.attempts):
        raise ParseError(f'manifest entry has out-of-range retryIndex: {retry_index!r}')
    if not isinstance(attachment_name, str) or not isinstance(part_name, str):
        raise ParseError('manifest entry "attachmentName" and "partName" must be strings')

    attempt = test.attempts[retry_index]
    # Multiple manifest entries can share the same attachmentName within
    # one retry attempt (e.g. two distinct screenshots both happened to
    # be named "screenshot.png" by the test code) - each still gets its
    # own ParsedAttachment/partName/Attachment row. No dedup: partName is
    # already the real uniqueness key (one per uploaded file part), name
    # is just display metadata and is allowed to collide. When more than
    # one raw attachment shares a name, dict lookup below picks whichever
    # was last in the report's own list - a second, independent source
    # (the view layer's uploaded_file.content_type) is preferred over
    # this value anyway, so this ambiguity doesn't surface in practice.
    #
    # content_type: looked up from this retry's own raw "attachments" by
    # name (design.md's non-blocking note - content-type can also come
    # from the multipart part itself, which the view layer prefers when
    # available; this is only the fallback for when it isn't). Default
    # to 'application/octet-stream' if the report itself never declared
    # this attachment (manifest and report disagreeing is not itself a
    # hard error - the file still gets stored).
    content_type = attempt._raw_attachments_by_name.get(attachment_name) or 'application/octet-stream'
    attempt.attachments.append(
        ParsedAttachment(part_name=part_name, name=attachment_name, content_type=content_type)
    )
